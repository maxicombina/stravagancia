"""Private physical inventory and temporal installations.

Call full_clean() in authorized write paths; save(), bulk writes and SQL do
not provide user authorization or validation of relationships.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.core.validators import RegexValidator
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.db import models
from django.db.models.functions import Floor, Lower
from django.utils import timezone

from .icons import ICON_KEYS
from .validators import CURRENCY_CODES, MAX_USAGE_VALUE, exact_usage_value, validate_currency

SOURCE_KINDS = ("fit", "strava")
GEAR_ID = RegexValidator(r"\A[A-Za-z0-9_-]{1,40}\Z", "Use a Strava gear identifier.", code="invalid_gear")


class OwnedResource(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if not self._state.adding:
            original_owner = type(self).objects.filter(pk=self.pk).values_list("owner_id", flat=True).first()
            if original_owner is not None and original_owner != self.owner_id:
                raise ValidationError({"owner": "The owner cannot be changed."})

    def __str__(self):
        return self.name


class Category(OwnedResource):
    name = models.CharField(max_length=100)
    notes = models.TextField(blank=True)
    is_archived = models.BooleanField(default=False)
    # garage-041: a key of garage.icons.ICON_CHOICES; empty means «deduce it from the names».
    icon = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        ordering = ("name", "id")
        verbose_name_plural = "categories"
        constraints = [
            models.CheckConstraint(condition=models.Q(name__regex=r"\S"), name="garage_category_name_nonblank"),
            models.UniqueConstraint("owner", Lower("name"), name="garage_category_owner_name_ci_unique"),
            # The shape of a key only: the list of icons can grow without a migration.
            models.CheckConstraint(condition=models.Q(icon="") | models.Q(icon__regex=r"^[a-z_]+$"),
                                   name="garage_category_icon_valid"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if isinstance(self.name, str):
            self.name = self.name.strip()
        if not self.name:
            errors["name"] = "Enter a nonempty name."
        if self.icon and self.icon not in ICON_KEYS:
            errors["icon"] = ValidationError("Choose one of the listed icons.", code="invalid_icon")
        if errors:
            raise ValidationError(errors)


class PhysicalInventory(OwnedResource):
    name = models.CharField(max_length=150)
    brand = models.CharField(max_length=150, blank=True)
    model = models.CharField(max_length=150, blank=True)
    serial_number = models.CharField(max_length=150, blank=True)
    acquired_on = models.DateField(null=True, blank=True)
    acquisition_anchor_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    purchase_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                          validators=[MinValueValidator(Decimal("0"))])
    purchase_currency = models.CharField(max_length=3, null=True, blank=True, validators=[validate_currency])

    class Meta:
        abstract = True
        ordering = ("name", "id")
        constraints = [
            models.CheckConstraint(condition=models.Q(name__regex=r"\S"), name="garage_%(class)s_name_nonblank"),
            models.CheckConstraint(
                condition=models.Q(purchase_amount__isnull=True) | (
                    models.Q(purchase_amount__gte=0) & models.Q(purchase_amount__lte=Decimal("9999999999.99"))),
                name="garage_%(class)s_purchase_amount_valid"),
            models.CheckConstraint(condition=(
                models.Q(purchase_amount__isnull=True, purchase_currency__isnull=True)
                | models.Q(purchase_amount__isnull=False, purchase_currency__isnull=False)),
                name="garage_%(class)s_purchase_pair"),
            models.CheckConstraint(condition=models.Q(purchase_currency__isnull=True)
                                  | models.Q(purchase_currency__in=sorted(CURRENCY_CODES)),
                                  name="garage_%(class)s_purchase_currency_valid"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if isinstance(self.name, str):
            self.name = self.name.strip()
        if not self.name:
            errors["name"] = "Enter a nonempty name."
        # HTML forms use an empty string for a missing optional currency.
        if self.purchase_currency == "":
            self.purchase_currency = None
        if (self.purchase_amount is None) != (self.purchase_currency is None):
            errors["purchase_currency"] = "Enter both a purchase amount and its currency, or neither."
        for field in ("acquisition_anchor_at", "retired_at"):
            value = getattr(self, field)
            if isinstance(value, datetime) and timezone.is_naive(value):
                errors[field] = "Enter an instant with an explicit time zone."
        if isinstance(self.retired_at, datetime) and timezone.is_aware(self.retired_at):
            field = "item" if isinstance(self, Item) else "bike"
            if RetirementInterval.objects.filter(owner_id=self.owner_id, **{field + "_id": self.pk}, ended_at__gt=self.retired_at).exists():
                errors["retired_at"] = ValidationError("A new open retirement cannot overlap recorded inactivity.", code="retirement_overlap")
        if errors:
            raise ValidationError(errors)


class Bike(PhysicalInventory):
    pass


class Item(PhysicalInventory):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")

    def clean(self):
        super().clean()
        if self.category_id and self.owner_id:
            category_owner = Category.objects.filter(pk=self.category_id).values_list("owner_id", flat=True).first()
            if category_owner is not None and category_owner != self.owner_id:
                raise ValidationError({"category": "Choose one of your own categories."})


class TsTzRange(models.Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class Installation(OwnedResource):
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="installations")
    bike = models.ForeignKey(Bike, on_delete=models.PROTECT, null=True, blank=True, related_name="installations")
    parent_item = models.ForeignKey(Item, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="child_installations")
    slot = models.CharField(max_length=80, null=True, blank=True, validators=[
        RegexValidator(r"\A[a-z0-9_]+\Z", "Use a lowercase ASCII position key.", code="invalid_slot")])
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("started_at", "id")
        constraints = [
            models.CheckConstraint(condition=(models.Q(bike__isnull=False, parent_item__isnull=True)
                                               | models.Q(bike__isnull=True, parent_item__isnull=False)),
                                   name="garage_installation_one_destination"),
            models.CheckConstraint(condition=models.Q(parent_item__isnull=True)
                                   | ~models.Q(parent_item=models.F("item")),
                                   name="garage_installation_not_own_parent"),
            models.CheckConstraint(condition=models.Q(ended_at__isnull=True)
                                   | models.Q(ended_at__gt=models.F("started_at")),
                                   name="garage_installation_positive_interval"),
            models.CheckConstraint(condition=models.Q(slot__isnull=True) | models.Q(slot__regex=r"^[a-z0-9_]+$"),
                                   name="garage_installation_canonical_slot"),
            ExclusionConstraint(name="garage_installation_item_no_overlap", expressions=[
                ("item", RangeOperators.EQUAL),
                (TsTzRange("started_at", "ended_at", RangeBoundary()), RangeOperators.OVERLAPS)]),
            ExclusionConstraint(name="garage_installation_bike_slot_no_overlap", expressions=[
                ("bike", RangeOperators.EQUAL), ("slot", RangeOperators.EQUAL),
                (TsTzRange("started_at", "ended_at", RangeBoundary()), RangeOperators.OVERLAPS)],
                condition=models.Q(bike__isnull=False, slot__isnull=False)),
            ExclusionConstraint(name="garage_installation_parent_slot_no_overlap", expressions=[
                ("parent_item", RangeOperators.EQUAL), ("slot", RangeOperators.EQUAL),
                (TsTzRange("started_at", "ended_at", RangeBoundary()), RangeOperators.OVERLAPS)],
                condition=models.Q(parent_item__isnull=False, slot__isnull=False)),
        ]

    def __str__(self):
        return f"{self.item_id} from {self.started_at}"

    def clean(self):
        super().clean()
        errors = {}
        if self.slot == "":
            self.slot = None
        if bool(self.bike_id) == bool(self.parent_item_id):
            errors["bike"] = ValidationError("Choose exactly one destination.", code="invalid_destination")
        if self.item_id and self.parent_item_id == self.item_id:
            errors["parent_item"] = ValidationError("An item cannot contain itself.", code="installation_cycle")
        for field in ("started_at", "ended_at"):
            value = getattr(self, field)
            if isinstance(value, datetime) and timezone.is_naive(value):
                errors[field] = ValidationError("Enter an instant with an explicit time zone.", code="invalid_instant")
        valid_start = isinstance(self.started_at, datetime) and timezone.is_aware(self.started_at)
        valid_end = self.ended_at is None or (isinstance(self.ended_at, datetime) and timezone.is_aware(self.ended_at))
        if valid_start and valid_end and self.ended_at is not None and self.ended_at <= self.started_at:
            errors["ended_at"] = ValidationError("The end must be later than the start.", code="invalid_interval")
        for field, model in (("item", Item), ("bike", Bike), ("parent_item", Item)):
            resource_id = getattr(self, field + "_id")
            if resource_id is None or self.owner_id is None:
                continue
            resource = model.objects.filter(pk=resource_id, owner_id=self.owner_id).first()
            if resource is None:
                errors[field] = ValidationError("Choose one of your own resources.", code="invalid_reference")
            elif resource.retired_at is not None and valid_start and valid_end:
                if (self.started_at >= resource.retired_at or self.ended_at is None
                        or self.ended_at > resource.retired_at):
                    errors[field] = ValidationError("The installation must finish by this resource's retirement.",
                                                    code="resource_retired")
            if resource is not None and valid_start and valid_end:
                interval_field = "bike" if model is Bike else "item"
                inactive = RetirementInterval.objects.filter(owner_id=self.owner_id, **{interval_field + "_id": resource_id}, ended_at__gt=self.started_at)
                if self.ended_at is not None:
                    inactive = inactive.filter(started_at__lt=self.ended_at)
                if inactive.exists():
                    errors[field] = ValidationError("The installation overlaps recorded inactivity.", code="resource_retired")
        if errors:
            raise ValidationError(errors)


class ServiceType(OwnedResource):
    name = models.CharField(max_length=100)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("name", "id")
        constraints = [
            models.CheckConstraint(condition=models.Q(name__regex=r"\S"), name="garage_servicetype_name_nonblank"),
            models.UniqueConstraint("owner", Lower("name"), name="garage_servicetype_owner_name_unique"),
        ]

    def clean(self):
        super().clean()
        if isinstance(self.name, str):
            self.name = self.name.strip()
        if not self.name:
            raise ValidationError({"name": "Enter a nonempty name."})


class ServiceTarget(OwnedResource):
    item = models.ForeignKey(Item, on_delete=models.PROTECT, null=True, blank=True)
    bike = models.ForeignKey(Bike, on_delete=models.PROTECT, null=True, blank=True)
    service_type = models.ForeignKey(ServiceType, on_delete=models.PROTECT)

    class Meta:
        abstract = True
        constraints = [models.CheckConstraint(condition=(models.Q(item__isnull=False, bike__isnull=True)
            | models.Q(item__isnull=True, bike__isnull=False)), name="garage_%(class)s_target_xor")]

    def __str__(self):
        return f"{self.service_type}: {self.item or self.bike}"

    def clean(self):
        super().clean()
        errors = {}
        if (self.item_id is None) == (self.bike_id is None):
            errors["item"] = "Choose exactly one item or bike."
        for field, model in (("item", Item), ("bike", Bike), ("service_type", ServiceType)):
            resource_id = getattr(self, field + "_id")
            if resource_id and not model.objects.filter(pk=resource_id, owner_id=self.owner_id).exists():
                errors[field] = "Choose one of your own resources."
        for field in ("performed_at", "anchor_at"):
            value = getattr(self, field, None)
            if value is not None and (not isinstance(value, datetime) or timezone.is_naive(value)):
                errors[field] = "Enter an instant with an explicit time zone."
        if errors:
            raise ValidationError(errors)


class ServiceEvent(ServiceTarget):
    performed_at = models.DateTimeField()
    notes = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                validators=[MinValueValidator(Decimal("0"))])
    currency = models.CharField(max_length=3, null=True, blank=True, validators=[validate_currency])

    def __str__(self):
        return f"{super().__str__()} · {self.performed_at.isoformat()}"

    class Meta(ServiceTarget.Meta):
        abstract = False
        ordering = ("-performed_at", "id")
        constraints = [*ServiceTarget.Meta.constraints,
            models.CheckConstraint(condition=models.Q(amount__isnull=True) | models.Q(amount__gte=0, amount__lte=Decimal("9999999999.99")), name="garage_serviceevent_amount_valid"),
            models.CheckConstraint(condition=(models.Q(amount__isnull=True, currency__isnull=True) | models.Q(amount__isnull=False, currency__isnull=False)), name="garage_serviceevent_money_pair"),
            models.CheckConstraint(condition=models.Q(currency__isnull=True) | models.Q(currency__in=sorted(CURRENCY_CODES)), name="garage_serviceevent_currency_valid"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.currency == "":
            self.currency = None
        if (self.amount is None) != (self.currency is None):
            errors["currency"] = "Enter both an amount and its currency, or neither."
        if isinstance(self.amount, (float, bool)):
            errors["amount"] = "Use a decimal amount, never a float."
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values("item_id", "bike_id", "service_type_id", "performed_at").first()
            if previous and UsageBaseline.objects.filter(service_event_id=self.pk).exists():
                if any(previous[k] != getattr(self, k) for k in previous):
                    errors["performed_at"] = "Correct or remove service readings before changing the event reference."
            if previous and Photo.objects.filter(service_event_id=self.pk).exists() and any(previous[k] != getattr(self, k) for k in ("item_id", "bike_id")):
                errors["item"] = "A photographed intervention cannot change its target."
        if errors:
            raise ValidationError(errors)


# Thresholds of a rule and amounts of a snooze; the first one reached wins.
# Decimal metres/seconds (exact, three decimals) and integer rides/days.
THRESHOLD_FIELDS = ("distance_m", "moving_time_s", "ride_count", "calendar_days", "elevation_gain_m")
DECIMAL_THRESHOLDS = ("distance_m", "moving_time_s", "elevation_gain_m")


def _any_threshold():
    condition = models.Q(**{f"{THRESHOLD_FIELDS[0]}__isnull": False})
    for field in THRESHOLD_FIELDS[1:]:
        condition |= models.Q(**{f"{field}__isnull": False})
    return condition


def _positive_threshold(field):
    return models.Q(**{f"{field}__isnull": True}) | models.Q(
        **{f"{field}__gt": 0, f"{field}__lte": MAX_USAGE_VALUE if field in DECIMAL_THRESHOLDS else 2147483647})


class MaintenanceRule(ServiceTarget):
    distance_m = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    moving_time_s = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    ride_count = models.PositiveIntegerField(null=True, blank=True)
    calendar_days = models.PositiveIntegerField(null=True, blank=True)
    anchor_at = models.DateTimeField(null=True, blank=True, help_text="Explicit initial reference when no intervention exists; unknown otherwise.")
    notes = models.TextField(blank=True)
    # garage-030 phase 3: positive elevation gain in metres since the reference (garage-037).
    elevation_gain_m = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)

    class Meta(ServiceTarget.Meta):
        abstract = False
        constraints = [*ServiceTarget.Meta.constraints,
            models.CheckConstraint(condition=_any_threshold(), name="garage_maintenancerule_has_threshold"),
            *[models.CheckConstraint(condition=_positive_threshold(field), name=f"garage_rule_{field}_positive") for field in THRESHOLD_FIELDS],
            models.UniqueConstraint(fields=("item", "service_type"), condition=models.Q(item__isnull=False), name="garage_rule_item_type_unique"),
            models.UniqueConstraint(fields=("bike", "service_type"), condition=models.Q(bike__isnull=False), name="garage_rule_bike_type_unique"),
        ]

    def clean_fields(self, exclude=None):
        exclude = set(exclude or ())
        errors = {}
        for field in ("ride_count", "calendar_days"):
            value = getattr(self, field)
            if field not in exclude and value is not None:
                try:
                    exact_usage_value(value, metric="ride_count")
                except ValidationError as error:
                    errors[field] = error.error_list
                    exclude.add(field)
        for field in DECIMAL_THRESHOLDS:
            if field not in exclude and getattr(self, field) is not None:
                try:
                    setattr(self, field, exact_usage_value(getattr(self, field)))
                except ValidationError as error:
                    errors[field] = error.error_list
                    exclude.add(field)
        try:
            super().clean_fields(exclude=exclude)
        except ValidationError as error:
            errors.update(error.error_dict)
        if errors:
            raise ValidationError(errors)

    def clean(self):
        super().clean()
        errors = {}
        fields = THRESHOLD_FIELDS
        if all(getattr(self, field) is None for field in fields):
            errors["distance_m"] = "Configure at least one independent threshold."
        for field in fields:
            value = getattr(self, field)
            if value is None:
                continue
            try:
                value = exact_usage_value(value, metric="ride_count" if field in ("ride_count", "calendar_days") else None)
                if value <= 0:
                    raise ValidationError("Enter a strictly positive threshold.")
            except ValidationError as error:
                errors[field] = error
        if errors:
            raise ValidationError(errors)


SNOOZE_AMOUNTS = THRESHOLD_FIELDS


class MaintenanceSnooze(OwnedResource):
    """A rule's alert postponed from `started_at` by km, hours, rides or days, whichever comes first (garage-034)."""
    rule = models.ForeignKey(MaintenanceRule, on_delete=models.CASCADE, related_name="snoozes")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True, help_text="Stopped by hand, replaced by a newer snooze or its rule moved; open otherwise.")
    # The rule's reference when it was postponed: any other reference (a new, edited or
    # backdated intervention, a changed anchor) means the count restarted and the snooze no longer applies.
    reference_at = models.DateTimeField()
    reference_event_id = models.UUIDField(null=True, blank=True)
    distance_m = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    moving_time_s = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    ride_count = models.PositiveIntegerField(null=True, blank=True)
    calendar_days = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    elevation_gain_m = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)

    class Meta:
        ordering = ("-started_at", "id")
        constraints = [
            models.CheckConstraint(condition=_any_threshold(), name="garage_snooze_has_amount"),
            *[models.CheckConstraint(condition=_positive_threshold(field), name=f"garage_snooze_{field}_positive") for field in SNOOZE_AMOUNTS],
            models.CheckConstraint(condition=models.Q(ended_at__isnull=True) | models.Q(ended_at__gte=models.F("started_at")),
                                   name="garage_snooze_ends_after_start"),
            models.UniqueConstraint(fields=("rule",), condition=models.Q(ended_at__isnull=True), name="garage_snooze_one_open_per_rule"),
        ]

    def __str__(self):
        return f"{self.rule_id} from {self.started_at}"

    def clean_fields(self, exclude=None):
        exclude = set(exclude or ())
        errors = {}
        for field in SNOOZE_AMOUNTS:
            value = getattr(self, field)
            if field in exclude or value is None:
                continue
            try:
                if field in ("ride_count", "calendar_days"):
                    exact_usage_value(value, metric="ride_count")
                else:
                    setattr(self, field, exact_usage_value(value))
            except ValidationError as error:
                errors[field] = error.error_list
                exclude.add(field)
        try:
            super().clean_fields(exclude=exclude)
        except ValidationError as error:
            errors.update(error.error_dict)
        if errors:
            raise ValidationError(errors)

    def clean(self):
        super().clean()
        errors = {}
        if all(getattr(self, field) is None for field in SNOOZE_AMOUNTS):
            errors["distance_m"] = "Configure at least one amount."
        for field in SNOOZE_AMOUNTS:
            value = getattr(self, field)
            if value is not None and value <= 0:
                errors[field] = "Enter a strictly positive amount."
        for field in ("started_at", "ended_at", "reference_at"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, datetime) or timezone.is_naive(value)):
                errors[field] = "Enter an instant with an explicit time zone."
        if (isinstance(self.started_at, datetime) and isinstance(self.ended_at, datetime) and "started_at" not in errors
                and "ended_at" not in errors and self.ended_at < self.started_at):
            errors["ended_at"] = "The end cannot be earlier than the start."
        if self.rule_id and self.owner_id and not MaintenanceRule.objects.filter(pk=self.rule_id, owner_id=self.owner_id).exists():
            errors["rule"] = "Choose one of your own resources."
        if errors:
            raise ValidationError(errors)


class UsageBaseline(OwnedResource):
    class Metric(models.TextChoices):
        DISTANCE = "distance_m", "Distance (metres)"
        MOVING_TIME = "moving_time_s", "Moving time (seconds)"
        RIDES = "ride_count", "Number of rides"

    class Scope(models.TextChoices):
        LIFETIME = "lifetime", "Lifetime"
        ACQUISITION = "acquisition", "Since acquisition"
        SERVICE = "service", "Since intervention"

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="usage_baselines")
    service_event = models.ForeignKey(ServiceEvent, on_delete=models.PROTECT, null=True, blank=True, related_name="usage_baselines")
    metric = models.CharField(max_length=20, choices=Metric.choices)
    scope = models.CharField(max_length=20, choices=Scope.choices)
    cut_at = models.DateTimeField()
    value = models.DecimalField(max_digits=20, decimal_places=3)
    source = models.CharField(max_length=80, default="manual")
    is_estimated = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("cut_at", "id")
        constraints = [
            models.CheckConstraint(condition=models.Q(metric__in=["distance_m", "moving_time_s", "ride_count"]),
                                   name="garage_baseline_valid_metric"),
            models.CheckConstraint(condition=models.Q(scope__in=["lifetime", "acquisition", "service"]),
                                   name="garage_baseline_valid_scope"),
            models.CheckConstraint(condition=models.Q(value__gte=0, value__lte=MAX_USAGE_VALUE),
                                   name="garage_baseline_finite_nonnegative_value"),
            models.CheckConstraint(condition=~models.Q(metric="ride_count") | models.Q(value=Floor("value")),
                                   name="garage_baseline_integer_ride_count"),
            models.CheckConstraint(condition=models.Q(source__regex=r"\S"), name="garage_baseline_source_nonblank"),
            models.UniqueConstraint(fields=("item", "metric", "scope", "cut_at"), condition=~models.Q(scope="service"), name="garage_baseline_unique_reading"),
            models.UniqueConstraint(fields=("item", "metric", "scope", "cut_at", "service_event"), condition=models.Q(scope="service"), name="garage_baseline_service_unique"),
            models.CheckConstraint(condition=(models.Q(scope="service", service_event__isnull=False) | (~models.Q(scope="service") & models.Q(service_event__isnull=True))), name="garage_baseline_service_scope"),
        ]

    def __str__(self):
        return f"{self.item_id}: {self.scope} {self.metric} at {self.cut_at}"

    def clean_fields(self, exclude=None):
        exclude = set(exclude or ())
        errors = {}
        if "value" not in exclude:
            try:
                self.value = exact_usage_value(self.value, metric=self.metric)
            except ValidationError as error:
                errors["value"] = error.error_list
                exclude.add("value")
        try:
            super().clean_fields(exclude=exclude)
        except ValidationError as error:
            errors.update(error.error_dict)
        if errors:
            raise ValidationError(errors)

    def clean(self):
        super().clean()
        errors = {}
        try:
            self.value = exact_usage_value(self.value, metric=self.metric)
        except ValidationError as error:
            errors["value"] = error
        if isinstance(self.source, str):
            self.source = self.source.strip()
        if not self.source:
            errors["source"] = ValidationError("Declare the reading's source.", code="invalid_source")
        valid_cut = isinstance(self.cut_at, datetime) and timezone.is_aware(self.cut_at)
        if self.cut_at is not None and not valid_cut:
            errors["cut_at"] = ValidationError("Enter an instant with an explicit time zone.", code="invalid_instant")
        if (self.scope == self.Scope.SERVICE) != (self.service_event_id is not None):
            errors["service_event"] = "Only service readings require an intervention."
        if self.service_event_id:
            event = ServiceEvent.objects.filter(pk=self.service_event_id, owner_id=self.owner_id, item_id=self.item_id).first()
            if event is None or event.item_id is None:
                errors["service_event"] = "Choose an intervention on this own item."
            elif valid_cut and self.cut_at < event.performed_at:
                errors["cut_at"] = "The reading cannot precede the intervention."
        if self.item_id and self.owner_id:
            item = Item.objects.filter(pk=self.item_id, owner_id=self.owner_id).first()
            if item is None:
                errors["item"] = ValidationError("Choose one of your own items.", code="invalid_reference")
            elif self.scope == self.Scope.ACQUISITION:
                if item.acquisition_anchor_at is None:
                    errors["scope"] = ValidationError("Confirm the acquisition instant before recording this scope.",
                                                      code="acquisition_anchor_required")
                elif valid_cut and self.cut_at < item.acquisition_anchor_at:
                    errors["cut_at"] = ValidationError("The reading cannot precede acquisition.", code="before_acquisition")
        if errors:
            raise ValidationError(errors)


class RideValues(models.Model):
    """Typed minimal observations; timer is never interpreted as movement."""
    started_at = models.DateTimeField(null=True, blank=True)
    name = models.CharField(max_length=150, blank=True)
    sport_type = models.CharField(max_length=150, blank=True)
    distance_m = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    moving_time_s = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    timer_time_s = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    elapsed_time_s = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    # garage-030 phase 3: positive elevation gain (m), power (W) and energy (kJ); unknown when NULL.
    elevation_gain_m = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    average_power_w = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    max_power_w = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    weighted_power_w = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    energy_kj = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)

    class Meta:
        abstract = True
        constraints = [models.CheckConstraint(
            condition=models.Q(**{f"{field}__isnull": True}) | models.Q(**{f"{field}__gte": 0, f"{field}__lte": MAX_USAGE_VALUE}),
            name=f"garage_%(class)s_{field}_valid") for field in
            ("distance_m", "moving_time_s", "timer_time_s", "elapsed_time_s",
             "elevation_gain_m", "average_power_w", "max_power_w", "weighted_power_w", "energy_kj")]

    def clean_fields(self, exclude=None):
        from .ride_values import RIDE_METRICS
        exclude = set(exclude or ())
        errors = {}
        for field in RIDE_METRICS:
            if field not in exclude and getattr(self, field) is not None:
                try:
                    setattr(self, field, exact_usage_value(getattr(self, field)))
                except ValidationError as error:
                    errors[field] = error.error_list
                    exclude.add(field)
        try:
            super().clean_fields(exclude=exclude)
        except ValidationError as error:
            errors.update(error.error_dict)
        if errors:
            raise ValidationError(errors)

    def clean(self):
        super().clean()
        from .ride_values import RIDE_METRICS
        errors = {}
        if self.started_at is not None and (not isinstance(self.started_at, datetime) or timezone.is_naive(self.started_at)):
            errors["started_at"] = ValidationError("Enter an aware instant.", code="invalid_instant")
        for field in RIDE_METRICS:
            if getattr(self, field) is not None:
                try:
                    setattr(self, field, exact_usage_value(getattr(self, field)))
                except ValidationError as error:
                    errors[field] = error
        if errors:
            raise ValidationError(errors)


class Ride(RideValues, OwnedResource):
    bike = models.ForeignKey(Bike, null=True, blank=True, on_delete=models.PROTECT, related_name="rides")
    notes = models.TextField(blank=True)
    manual_overrides = models.JSONField(default=dict, blank=True)
    field_provenance = models.JSONField(default=dict, blank=True)

    class Meta(RideValues.Meta):
        abstract = False
        ordering = ("started_at", "id")

    @property
    def has_known_start(self):
        """A withdrawn source-only ride remains inspectable, with no usable start."""
        return self.started_at is not None

    def clean(self):
        super().clean()
        from .ride_values import decode_manual, validate_provenance
        errors = {}
        for field, validate in (("manual_overrides", decode_manual), ("field_provenance", validate_provenance)):
            try:
                validate(getattr(self, field))
            except ValidationError as error:
                errors[field] = error
        if self.bike_id and not Bike.objects.filter(pk=self.bike_id, owner_id=self.owner_id).exists():
            errors["bike"] = ValidationError("Choose one of your own bikes.", code="invalid_reference")
        if "field_provenance" not in errors:
            # One query for every referenced source (garage-030 review: was one query per field).
            referenced = {(str(uuid.UUID(entry["source_id"])), entry["kind"]) for entry in self.field_provenance.values()
                          if entry["kind"] in SOURCE_KINDS}
            if referenced:
                active = {(str(pk), kind) for pk, kind in ActivitySource.objects.filter(
                    pk__in={source_id for source_id, _ in referenced}, owner_id=self.owner_id, ride_id=self.pk,
                    withdrawn_at__isnull=True).values_list("pk", "source_kind")}
                if not referenced <= active:
                    errors["field_provenance"] = ValidationError("Provenance must reference an active source of this ride.", code="invalid_reference")
        # Manual JSON cannot preserve a bike after its protected FK is removed.
        try:
            manual_bike = decode_manual(self.manual_overrides).get("bike")
            if manual_bike is not None and manual_bike != self.bike_id:
                errors["manual_overrides"] = ValidationError("Manual bike must match the protected bike field.", code="invalid_reference")
        except ValidationError:
            pass
        if errors:
            raise ValidationError(errors)


class JsonArrayLength(models.Func):
    function = "JSONB_ARRAY_LENGTH"
    output_field = models.IntegerField()


class ImportRun(OwnedResource):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    source_kind = models.CharField(max_length=10, default="fit", editable=False)
    file_hash = models.CharField(max_length=64, blank=True, default="", editable=False)
    session_indices = models.JSONField(default=list, blank=True, editable=False)
    requested_from = models.DateTimeField(null=True, blank=True)
    requested_to = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    total = models.PositiveIntegerField(null=True, blank=True)
    processed = models.PositiveIntegerField(default=0)
    cursor = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    # Strava history (garage-030): activities stored or skipped; NULL for FIT jobs.
    items_imported = models.PositiveIntegerField(null=True, blank=True)
    items_skipped = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.CheckConstraint(condition=models.Q(source_kind__in=list(SOURCE_KINDS)), name="garage_importrun_source_valid"),
            # A Strava job has no file manifest: processed = cursor = confirmed pages, total unknown.
            models.CheckConstraint(condition=~models.Q(source_kind="strava") | models.Q(file_hash="", total__isnull=True),
                                   name="garage_importrun_strava_pages"),
            models.CheckConstraint(condition=models.Q(file_hash="", session_indices=[]) | (
                models.Q(file_hash__regex=r"\A[0-9a-f]{64}\Z", total__isnull=False)
                & ~models.Q(session_indices=[]) & models.Q(total=JsonArrayLength("session_indices"))), name="garage_importrun_manifest_pair"),
            models.CheckConstraint(condition=models.Q(state__in=["pending", "running", "paused", "completed", "failed", "cancelled"]), name="garage_importrun_state_valid"),
            models.CheckConstraint(condition=models.Q(total__isnull=True) | models.Q(processed__lte=models.F("total")), name="garage_importrun_progress_bounded"),
            models.CheckConstraint(condition=models.Q(cursor__lte=models.F("processed")), name="garage_importrun_cursor_bounded"),
            models.CheckConstraint(condition=~models.Q(state="completed") | models.Q(cursor=models.F("processed")), name="garage_importrun_completed_cursor"),
            models.CheckConstraint(condition=~models.Q(state="completed") | models.Q(total__isnull=True) | models.Q(processed=models.F("total")), name="garage_importrun_completed_progress"),
            models.CheckConstraint(condition=models.Q(requested_from__isnull=True) | models.Q(requested_to__isnull=True) | models.Q(requested_from__lt=models.F("requested_to")), name="garage_importrun_interval_valid"),
        ]

    def __str__(self):
        return f"{'Strava' if self.source_kind == 'strava' else 'FIT'} import {self.pk}: {self.state}"

    def clean(self):
        super().clean()
        from .ride_values import validate_run_errors, validate_run_manifest
        errors = {}
        try:
            validate_run_manifest(self.file_hash, self.session_indices, self.total)
        except ValidationError as error:
            errors["session_indices"] = error
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values("file_hash", "session_indices").first()
            if original and any(original[field] != getattr(self, field) for field in original):
                errors["session_indices"] = ValidationError("An import manifest cannot be changed.", code="immutable_manifest")
        for field in ("requested_from", "requested_to"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, datetime) or timezone.is_naive(value)):
                errors[field] = ValidationError("Enter an aware instant.", code="invalid_instant")
        try:
            validate_run_errors(self.errors)
        except ValidationError as error:
            errors["errors"] = error
        if errors:
            raise ValidationError(errors)


class ActivitySource(RideValues, OwnedResource):
    started_at = models.DateTimeField()
    ride = models.ForeignKey(Ride, on_delete=models.CASCADE, related_name="sources")
    import_run = models.ForeignKey(ImportRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="sources")
    source_kind = models.CharField(max_length=10, default="fit", editable=False)
    file_hash = models.CharField(max_length=64, validators=[RegexValidator(r"\A[0-9a-f]{64}\Z", code="invalid_hash")])
    session_index = models.PositiveIntegerField()
    parser_version = models.CharField(max_length=64, validators=[RegexValidator(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z", code="invalid_parser_version")])
    observations_updated_at = models.DateTimeField(default=timezone.now, editable=False)
    withdrawn_at = models.DateTimeField(null=True, blank=True, editable=False)
    # Strava (garage-030): activity id (identity, immutable) and the observed gear; FIT keeps NULL/blank.
    external_id = models.BigIntegerField(null=True, blank=True, editable=False)
    gear_id = models.CharField(max_length=40, blank=True, validators=[GEAR_ID])
    # Arrived matching several rides (or one that already had this class): never joined automatically.
    possible_duplicate = models.BooleanField(default=False, editable=False)

    class Meta(RideValues.Meta):
        abstract = False
        constraints = [*RideValues.Meta.constraints,
            models.CheckConstraint(condition=models.Q(source_kind__in=list(SOURCE_KINDS)), name="garage_activitysource_kind_valid"),
            models.CheckConstraint(condition=(models.Q(source_kind="fit", external_id__isnull=True, gear_id="")
                                              | models.Q(source_kind="strava", external_id__isnull=False, external_id__gt=0, session_index=0)),
                                   name="garage_activitysource_external_identity"),
            models.CheckConstraint(condition=models.Q(gear_id="") | models.Q(gear_id__regex=r"^[A-Za-z0-9_-]{1,40}$"),
                                   name="garage_activitysource_gear_valid"),
            models.UniqueConstraint(fields=("owner", "external_id"), condition=models.Q(source_kind="strava"),
                                    name="garage_activitysource_strava_unique"),
            models.CheckConstraint(condition=models.Q(file_hash__regex=r"\A[0-9a-f]{64}\Z"), name="garage_activitysource_hash_valid"),
            models.CheckConstraint(condition=models.Q(parser_version__regex=r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z"), name="garage_activitysource_parser_valid"),
            models.UniqueConstraint(fields=("owner", "file_hash", "session_index"), name="garage_activitysource_identity_unique"),
        ]

    def __str__(self):
        if self.source_kind == "strava":
            return f"Strava activity {self.external_id}: {self.pk}"
        return f"FIT session {self.session_index}: {self.pk}"

    def clean(self):
        super().clean()
        errors = {}
        if self.ride_id and not Ride.objects.filter(pk=self.ride_id, owner_id=self.owner_id).exists():
            errors["ride"] = ValidationError("Choose one of your own resources.", code="invalid_reference")
        if self.import_run_id:
            run = ImportRun.objects.filter(pk=self.import_run_id, owner_id=self.owner_id).only("file_hash", "session_indices", "source_kind").first()
            if run is None:
                errors["import_run"] = ValidationError("Choose one of your own resources.", code="invalid_reference")
            if run is not None and run.file_hash and (run.file_hash != self.file_hash or self.session_index not in run.session_indices):
                errors["import_run"] = ValidationError("The source must belong to its job manifest.", code="manifest_mismatch")
            if run is not None and run.source_kind != self.source_kind:
                errors["import_run"] = ValidationError("The source must belong to a job of its own kind.", code="manifest_mismatch")
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values("ride_id", "file_hash", "session_index", "source_kind", "external_id").first()
            # Only the explicit separate/join service may move a source to another ride.
            movable = {"ride_id"} if getattr(self, "_allow_ride_move", False) else set()
            if original and any(original[field] != getattr(self, field) for field in original if field not in movable):
                errors["ride"] = ValidationError("Source identity and ride cannot be changed.", code="immutable_field")
        if errors:
            raise ValidationError(errors)


class UsageProfile(OwnedResource):
    """One immutable membership version in a profile series; [start, end)."""
    series_id = models.UUIDField(default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    bike = models.ForeignKey(Bike, null=True, blank=True, on_delete=models.PROTECT, related_name="usage_profiles")
    sport_type = models.CharField(max_length=80, blank=True,
        validators=[RegexValidator(r"\A[a-z0-9_]*\Z", code="invalid_sport_type")])
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    items = models.ManyToManyField(Item, through="UsageProfileItem", related_name="usage_profiles")

    class Meta:
        ordering = ("started_at", "id")
        constraints = [
            models.CheckConstraint(condition=models.Q(name__regex=r"\S"), name="garage_usageprofile_name_nonblank"),
            models.CheckConstraint(condition=models.Q(sport_type__regex=r"\A[a-z0-9_]*\Z"), name="garage_usageprofile_sport_canonical"),
            models.CheckConstraint(condition=models.Q(ended_at__isnull=True) | models.Q(ended_at__gt=models.F("started_at")), name="garage_usageprofile_interval_positive"),
            ExclusionConstraint(name="garage_usageprofile_series_no_overlap", expressions=[
                ("owner", RangeOperators.EQUAL), ("series_id", RangeOperators.EQUAL),
                (TsTzRange("started_at", "ended_at", RangeBoundary()), RangeOperators.OVERLAPS)]),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if isinstance(self.name, str):
            self.name = self.name.strip()
        if not self.name:
            errors["name"] = ValidationError("Enter a profile name.", code="invalid_name")
        if isinstance(self.sport_type, str):
            self.sport_type = self.sport_type.strip().lower()
        for field in ("started_at", "ended_at"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, datetime) or timezone.is_naive(value)):
                errors[field] = ValidationError("Enter an aware instant.", code="invalid_instant")
        if (isinstance(self.started_at, datetime) and isinstance(self.ended_at, datetime)
                and "started_at" not in errors and "ended_at" not in errors and self.ended_at <= self.started_at):
            errors["ended_at"] = ValidationError("The end must be later than the start.", code="invalid_interval")
        if self.bike_id and not Bike.objects.filter(pk=self.bike_id, owner_id=self.owner_id).exists():
            errors["bike"] = ValidationError("Choose one of your own bikes.", code="invalid_reference")
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values_list("series_id", flat=True).first()
            if original is not None and original != self.series_id:
                errors["series_id"] = ValidationError("The profile series cannot be changed.", code="immutable_field")
        if errors:
            raise ValidationError(errors)


class UsageProfileItem(OwnedResource):
    profile = models.ForeignKey(UsageProfile, on_delete=models.CASCADE, related_name="memberships")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="profile_memberships")

    class Meta:
        constraints = [models.UniqueConstraint(fields=("profile", "item"), name="garage_usageprofileitem_unique")]

    def __str__(self):
        return f"{self.profile_id}: {self.item_id}"

    def clean(self):
        super().clean()
        errors = {}
        for field, model in (("profile", UsageProfile), ("item", Item)):
            resource_id = getattr(self, field + "_id")
            if resource_id and not model.objects.filter(pk=resource_id, owner_id=self.owner_id).exists():
                errors[field] = ValidationError("Choose one of your own resources.", code="invalid_reference")
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values("profile_id", "item_id").first()
            if original and any(original[field] != getattr(self, field) for field in original):
                errors["profile"] = ValidationError("Membership identity cannot be changed.", code="immutable_field")
        if errors:
            raise ValidationError(errors)


class UsageOverride(OwnedResource):
    class Action(models.TextChoices):
        INCLUDE = "include", "Include"
        EXCLUDE = "exclude", "Exclude"

    ride = models.ForeignKey(Ride, on_delete=models.CASCADE, related_name="usage_overrides")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="usage_overrides")
    action = models.CharField(max_length=7, choices=Action.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("ride", "item"), name="garage_usageoverride_unique"),
            models.CheckConstraint(condition=models.Q(action__in=["include", "exclude"]), name="garage_usageoverride_action_valid"),
        ]

    def __str__(self):
        return f"{self.ride_id}: {self.action} {self.item_id}"

    def clean(self):
        super().clean()
        errors = {}
        for field, model in (("ride", Ride), ("item", Item)):
            resource_id = getattr(self, field + "_id")
            if resource_id and not model.objects.filter(pk=resource_id, owner_id=self.owner_id).exists():
                errors[field] = ValidationError("Choose one of your own resources.", code="invalid_reference")
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values("ride_id", "item_id").first()
            if original and any(original[field] != getattr(self, field) for field in original):
                errors["ride"] = ValidationError("Override identity cannot be changed.", code="immutable_field")
        if errors:
            raise ValidationError(errors)


class RetirementInterval(OwnedResource):
    """Closed real inactivity periods survive reactivation and reconstruction."""
    item = models.ForeignKey(Item, null=True, blank=True, on_delete=models.PROTECT, related_name="retirement_intervals")
    bike = models.ForeignKey(Bike, null=True, blank=True, on_delete=models.PROTECT, related_name="retirement_intervals")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()

    class Meta:
        ordering = ("started_at", "id")
        constraints = [
            models.CheckConstraint(condition=(models.Q(item__isnull=False, bike__isnull=True)
                | models.Q(item__isnull=True, bike__isnull=False)), name="garage_retirementinterval_destination_xor"),
            models.CheckConstraint(condition=models.Q(ended_at__gt=models.F("started_at")), name="garage_retirementinterval_positive"),
            ExclusionConstraint(name="garage_retirementinterval_item_no_overlap", condition=models.Q(item__isnull=False),
                expressions=[("item", RangeOperators.EQUAL), (TsTzRange("started_at", "ended_at", RangeBoundary()), RangeOperators.OVERLAPS)]),
            ExclusionConstraint(name="garage_retirementinterval_bike_no_overlap", condition=models.Q(bike__isnull=False),
                expressions=[("bike", RangeOperators.EQUAL), (TsTzRange("started_at", "ended_at", RangeBoundary()), RangeOperators.OVERLAPS)]),
        ]

    def __str__(self):
        return f"{self.item_id or self.bike_id}: [{self.started_at}, {self.ended_at})"

    def clean(self):
        super().clean()
        errors = {}
        if (self.item_id is None) == (self.bike_id is None):
            errors["item"] = ValidationError("Choose exactly one resource.", code="invalid_destination")
        valid = True
        for field in ("started_at", "ended_at"):
            value = getattr(self, field)
            if not isinstance(value, datetime) or timezone.is_naive(value):
                errors[field] = ValidationError("Enter an aware instant.", code="invalid_instant")
                valid = False
        if valid and self.ended_at <= self.started_at:
            errors["ended_at"] = ValidationError("The end must be later than retirement.", code="invalid_interval")
            valid = False
        for field, model in (("item", Item), ("bike", Bike)):
            resource_id = getattr(self, field + "_id")
            if resource_id is None:
                continue
            if not model.objects.filter(pk=resource_id, owner_id=self.owner_id).exists():
                errors[field] = ValidationError("Choose your own resource.", code="invalid_reference")
            elif valid:
                relation = models.Q(item_id=resource_id) | models.Q(parent_item_id=resource_id) if field == "item" else models.Q(bike_id=resource_id)
                if Installation.objects.filter(owner_id=self.owner_id).filter(relation, started_at__lt=self.ended_at).filter(
                        models.Q(ended_at__isnull=True) | models.Q(ended_at__gt=self.started_at)).exists():
                    errors[field] = ValidationError("Correct installations in the inactive period first.", code="retirement_conflict")
        if errors:
            raise ValidationError(errors)


class ItemUsage(OwnedResource):
    """Effective per-item/per-ride facts, never an incremental lifetime counter."""
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="usages")
    ride = models.ForeignKey(Ride, on_delete=models.CASCADE, related_name="item_usages")
    started_at = models.DateTimeField()
    bike = models.ForeignKey(Bike, null=True, blank=True, on_delete=models.PROTECT, related_name="item_usages")
    distance_m = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    moving_time_s = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    timer_time_s = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    elapsed_time_s = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    ride_count = models.PositiveSmallIntegerField(default=1)
    # garage-030 phase 3: the ride's elevation gain, whole, like its distance; power is never materialized.
    elevation_gain_m = models.DecimalField(max_digits=20, decimal_places=3, null=True, blank=True)
    resolution = models.JSONField(default=list)
    field_provenance = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("started_at", "id")
        indexes = [models.Index(fields=("owner", "item", "started_at"), name="garage_usage_item_time_ix"),
                   models.Index(fields=("owner", "started_at", "ride"), name="garage_usage_window_ix")]
        constraints = [
            models.UniqueConstraint(fields=("ride", "item"), name="garage_itemusage_unique"),
            models.CheckConstraint(condition=models.Q(ride_count=1), name="garage_itemusage_one_ride"),
            *[models.CheckConstraint(condition=models.Q(**{f"{field}__isnull": True}) | models.Q(
                **{f"{field}__gte": 0, f"{field}__lte": MAX_USAGE_VALUE}), name=f"garage_itemusage_{field}_valid")
                for field in ("distance_m", "moving_time_s", "timer_time_s", "elapsed_time_s", "elevation_gain_m")],
        ]

    def __str__(self):
        return f"{self.item_id}: {self.ride_id}"

    def clean_fields(self, exclude=None):
        exclude = set(exclude or ())
        errors = {}
        if "ride_count" not in exclude and (type(self.ride_count) is not int or self.ride_count != 1):
            errors["ride_count"] = [ValidationError("Each effective ride counts exactly once.", code="invalid_ride_count")]
            exclude.add("ride_count")
        from .ride_values import USAGE_METRICS
        for field in USAGE_METRICS:
            value = getattr(self, field)
            if field not in exclude and value is not None:
                try:
                    setattr(self, field, exact_usage_value(value))
                except ValidationError as error:
                    errors[field] = error.error_list
                    exclude.add(field)
        try:
            super().clean_fields(exclude=exclude)
        except ValidationError as error:
            errors.update(error.error_dict)
        if errors:
            raise ValidationError(errors)

    def clean(self):
        super().clean()
        from .ride_values import USAGE_METRICS, validate_provenance
        errors = {}
        for field, model in (("item", Item), ("ride", Ride), ("bike", Bike)):
            resource_id = getattr(self, field + "_id")
            if resource_id and not model.objects.filter(pk=resource_id, owner_id=self.owner_id).exists():
                errors[field] = ValidationError("Choose one of your own resources.", code="invalid_reference")
        if not isinstance(self.started_at, datetime) or timezone.is_naive(self.started_at):
            errors["started_at"] = ValidationError("Enter an aware start.", code="invalid_instant")
        for field in USAGE_METRICS:
            value = getattr(self, field)
            if value is not None:
                try:
                    setattr(self, field, exact_usage_value(value))
                except ValidationError as error:
                    errors[field] = error
        if type(self.ride_count) is not int or self.ride_count != 1:
            errors["ride_count"] = ValidationError("Each effective ride counts exactly once.", code="invalid_ride_count")
        try:
            validate_provenance(self.field_provenance)
        except ValidationError as error:
            errors["field_provenance"] = error
        if "field_provenance" not in errors:
            for entry in self.field_provenance.values():
                if entry["kind"] in SOURCE_KINDS and not ActivitySource.objects.filter(
                        pk=entry["source_id"], owner_id=self.owner_id, ride_id=self.ride_id, withdrawn_at__isnull=True,
                        source_kind=entry["kind"]).exists():
                    errors["field_provenance"] = ValidationError("Use an active source of this own ride.", code="invalid_reference")
        try:
            if not isinstance(self.resolution, list) or not self.resolution:
                raise ValueError
            for reason in self.resolution:
                if not isinstance(reason, dict) or set(reason) != {"kind", "resource_id", "root_item_id"}:
                    raise ValueError
                kind = reason["kind"]
                if not isinstance(kind, str) or kind not in {"profile", "bike_installation", "manual_include"}:
                    raise ValueError
                resource_id, root_id = uuid.UUID(reason["resource_id"]), uuid.UUID(reason["root_item_id"])
                model = {"profile": UsageProfile, "bike_installation": Installation, "manual_include": UsageOverride}[kind]
                references = model.objects.filter(pk=resource_id, owner_id=self.owner_id)
                if kind == "manual_include":
                    references = references.filter(ride_id=self.ride_id, action="include")
                if not references.exists() or not Item.objects.filter(pk=root_id, owner_id=self.owner_id).exists():
                    raise ValueError
        except (ValueError, TypeError, AttributeError):
            errors["resolution"] = ValidationError("Use validated own resolution reasons.", code="invalid_resolution")
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values("item_id", "ride_id").first()
            if original and any(original[field] != getattr(self, field) for field in original):
                errors["item"] = ValidationError("Effective usage identity cannot be changed.", code="immutable_field")
        if errors:
            raise ValidationError(errors)


class UsageMaterializationState(OwnedResource):
    """Initialization only; completeness of real-world history is independent."""
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, editable=False,
                                related_name="garage_usage_materialization")
    initialized_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Usage initialized for owner {self.owner_id}: {self.initialized_at}"


class PhotoStorageBudget(models.Model):
    """Singleton row serializes project-wide byte reservations."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="garage_photo_budget_singleton")]


class PhotoStorageObject(OwnedResource):
    """Committed reservation and durable cleanup job, including ambiguous PUTs.

    All rows count towards quota until DELETE and removal of this row succeed.
    PROTECT retains cleanup information if an account deletion is attempted.
    """
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    key = models.CharField(max_length=64, unique=True, editable=False,
        validators=[RegexValidator(r"\Agarage/photos/[0-9a-f]{32}\.webp\Z", "Use an internal photo key.")])
    size_bytes = models.PositiveIntegerField(editable=False)
    width = models.PositiveSmallIntegerField(editable=False)
    height = models.PositiveSmallIntegerField(editable=False)
    sha256 = models.CharField(max_length=64, editable=False,
        validators=[RegexValidator(r"\A[0-9a-f]{64}\Z", "Use a server-calculated checksum.")])
    state = models.CharField(max_length=8, choices=[("reserved", "Reserved"), ("live", "Live"), ("cleanup", "Cleanup")],
                             default="reserved", editable=False)
    cleanup_after = models.DateTimeField(null=True, blank=True, editable=False)
    cleanup_attempts = models.PositiveIntegerField(default=0, editable=False)
    cleanup_error_code = models.CharField(max_length=40, blank=True, editable=False)

    class Meta:
        indexes = [models.Index(fields=["state", "cleanup_after"], name="garage_photo_cleanup_due")]
        constraints = [
            models.CheckConstraint(condition=models.Q(key__regex=r"^garage/photos/[0-9a-f]{32}\.webp$"),
                                   name="garage_photo_object_key"),
            models.CheckConstraint(condition=models.Q(size_bytes__gt=0, size_bytes__lte=15 * 1024 * 1024),
                                   name="garage_photo_object_bytes"),
            models.CheckConstraint(condition=models.Q(width__gt=0, width__lte=2000, height__gt=0, height__lte=2000),
                                   name="garage_photo_object_dimensions"),
            models.CheckConstraint(condition=models.Q(sha256__regex=r"^[0-9a-f]{64}$"), name="garage_photo_object_sha256"),
            models.CheckConstraint(condition=(models.Q(state="live", cleanup_after__isnull=True)
                | models.Q(state__in=["reserved", "cleanup"], cleanup_after__isnull=False)),
                name="garage_photo_object_cleanup_state"),
        ]

    def __str__(self):
        return "Private photo storage object"

    def clean(self):
        super().clean()
        if not self._state.adding:
            fields = ("key", "size_bytes", "width", "height", "sha256")
            original = type(self).objects.filter(pk=self.pk).values(*fields).first()
            if original and any(original[name] != getattr(self, name) for name in fields):
                raise ValidationError("Stored photo identity and metadata cannot be changed.", code="immutable_field")


class Photo(OwnedResource):
    """An owner-scoped reference to one processed object and one inventory target."""
    bike = models.ForeignKey(Bike, on_delete=models.PROTECT, null=True, blank=True, related_name="photos")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, null=True, blank=True, related_name="photos")
    service_event = models.ForeignKey(ServiceEvent, on_delete=models.PROTECT, null=True, blank=True, related_name="photos")
    storage_object = models.OneToOneField(PhotoStorageObject, on_delete=models.PROTECT, related_name="photo")

    class Meta:
        ordering = ("created_at", "pk")
        constraints = [models.CheckConstraint(condition=(models.Q(bike__isnull=False, item__isnull=True, service_event__isnull=True)
            | models.Q(bike__isnull=True, item__isnull=False, service_event__isnull=True)
            | models.Q(bike__isnull=True, item__isnull=True, service_event__isnull=False)), name="garage_photo_one_target")]

    def __str__(self):
        return "Private photo"

    def clean(self):
        super().clean()
        errors = {}
        for field, model in (("bike", Bike), ("item", Item), ("service_event", ServiceEvent), ("storage_object", PhotoStorageObject)):
            resource_id = getattr(self, field + "_id")
            if resource_id and not model.objects.filter(pk=resource_id, owner_id=self.owner_id).exists():
                errors[field] = "Choose an own photo resource."
        if self.storage_object_id and not PhotoStorageObject.objects.filter(pk=self.storage_object_id, state="live").exists():
            errors["storage_object"] = "The photo object must be live."
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values("bike_id", "item_id", "service_event_id").first()
            if original and any(original[name] != getattr(self, name) for name in original):
                errors["bike"] = "The photo target cannot be changed."
        if errors:
            raise ValidationError(errors)


STRAVA_ERROR_CODES = ("", "unauthorized", "rate_limited", "network", "invalid_response", "not_found", "athlete_taken", "unexpected_failure")


class StravaAccount(OwnedResource):
    """The owner's Strava athlete (garage-030). Token mode keeps no token here.

    mode='env' reuses Stravagancia's refresh token through
    strava_integration.utils.refresh_access_token(); 'oauth' is reserved for
    garage-040 (per-user encrypted tokens). Never in admin, logs or export.
    """
    class Mode(models.TextChoices):
        ENV = "env", "Token de Stravagancia"
        OAUTH = "oauth", "OAuth por usuario"

    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, editable=False,
                                 related_name="garage_strava_account")
    athlete_id = models.BigIntegerField(unique=True)
    athlete_name = models.CharField(max_length=150, blank=True)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.ENV)
    scopes = models.CharField(max_length=200, blank=True)
    access_token_enc = models.TextField(blank=True, editable=False)
    refresh_token_enc = models.TextField(blank=True, editable=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    connected_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=20, blank=True)
    last_error_code = models.CharField(max_length=40, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(mode__in=["env", "oauth"]), name="garage_stravaaccount_mode_valid"),
            models.CheckConstraint(condition=models.Q(athlete_id__gt=0), name="garage_stravaaccount_athlete_positive"),
            models.CheckConstraint(condition=~models.Q(mode="env") | models.Q(access_token_enc="", refresh_token_enc=""),
                                   name="garage_stravaaccount_env_no_tokens"),
            models.CheckConstraint(condition=models.Q(last_sync_status__in=["", "ok", "partial", "failed"]),
                                   name="garage_stravaaccount_status_valid"),
            models.CheckConstraint(condition=models.Q(last_error_code__in=list(STRAVA_ERROR_CODES)),
                                   name="garage_stravaaccount_error_valid"),
        ]

    def __str__(self):
        return f"Strava athlete {self.athlete_id}"

    @property
    def can_confirm_deletes(self):
        """Without activity:read_all a private activity also answers 404."""
        return "activity:read_all" in self.scopes.split(",")

    def clean(self):
        super().clean()
        errors = {}
        for field in ("expires_at", "connected_at", "revoked_at", "last_sync_at"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, datetime) or timezone.is_naive(value)):
                errors[field] = ValidationError("Enter an aware instant.", code="invalid_instant")
        if self.mode == self.Mode.ENV and (self.access_token_enc or self.refresh_token_enc):
            errors["mode"] = ValidationError("Token mode stores no token.", code="invalid_mode")
        if errors:
            raise ValidationError(errors)


class StravaGear(OwnedResource):
    """A Strava gear id of this owner and the Garage bike it stands for.

    No FK to StravaAccount: the link survives removing and re-adding the account.
    """
    gear_id = models.CharField(max_length=40, validators=[GEAR_ID])
    name = models.CharField(max_length=150, blank=True)
    retired = models.BooleanField(default=False)
    bike = models.ForeignKey(Bike, null=True, blank=True, on_delete=models.PROTECT, related_name="strava_gear")

    class Meta:
        ordering = ("retired", "name", "gear_id")
        constraints = [
            models.UniqueConstraint(fields=("owner", "gear_id"), name="garage_stravagear_owner_gear_unique"),
            models.CheckConstraint(condition=models.Q(gear_id__regex=r"^[A-Za-z0-9_-]{1,40}$"), name="garage_stravagear_gear_valid"),
        ]

    def __str__(self):
        return self.name or self.gear_id

    def clean(self):
        super().clean()
        errors = {}
        if self.bike_id and not Bike.objects.filter(pk=self.bike_id, owner_id=self.owner_id).exists():
            errors["bike"] = ValidationError("Choose one of your own bikes.", code="invalid_reference")
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values_list("gear_id", flat=True).first()
            if original is not None and original != self.gear_id:
                errors["gear_id"] = ValidationError("The gear identifier cannot be changed.", code="immutable_field")
        if errors:
            raise ValidationError(errors)


class StravaEvent(models.Model):
    """A webhook hint persisted before answering Strava; never an order.

    No owner: only events of athletes with a StravaAccount are stored. A delete
    is confirmed through the API before anything is withdrawn. Purged after 30 days.
    """
    subscription_id = models.BigIntegerField()
    athlete_id = models.BigIntegerField()
    object_type = models.CharField(max_length=10)
    aspect_type = models.CharField(max_length=10)
    object_id = models.BigIntegerField()
    event_time = models.DateTimeField()
    updates = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=40, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("event_time", "id")
        indexes = [models.Index(fields=("athlete_id", "processed_at"), name="garage_stravaevent_pending_ix")]
        constraints = [
            models.UniqueConstraint(fields=("subscription_id", "athlete_id", "object_id", "aspect_type", "event_time"),
                                    name="garage_stravaevent_dedupe"),
            models.CheckConstraint(condition=models.Q(object_type__in=["activity", "athlete"]), name="garage_stravaevent_object_valid"),
            models.CheckConstraint(condition=models.Q(aspect_type__in=["create", "update", "delete"]), name="garage_stravaevent_aspect_valid"),
            models.CheckConstraint(condition=models.Q(athlete_id__gt=0, object_id__gt=0), name="garage_stravaevent_ids_positive"),
        ]

    def __str__(self):
        return f"Strava {self.aspect_type} {self.object_type} {self.object_id}"
