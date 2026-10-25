from django import forms


class PhotoUploadForm(forms.Form):
    photo = forms.FileField(label="Foto", widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        help_text="JPEG, PNG o WebP estática, hasta 15 MiB. Se guarda comprimida, sin metadatos y hasta 2000 píxeles.")
