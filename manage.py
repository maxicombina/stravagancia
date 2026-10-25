#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        from test_support.isolation import install, validate_settings_choice
        for index, arg in enumerate(sys.argv[1:], start=1):
            flag = arg.split("=", 1)[0]
            # argparse accepts abbreviations such as --sett; validate those too.
            if flag.startswith("--") and len(flag) > 2 and "--settings".startswith(flag):
                if "=" in arg:
                    validate_settings_choice(arg.split("=", 1)[1])
                elif index + 1 < len(sys.argv):
                    validate_settings_choice(sys.argv[index + 1])
        install()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'strava_app.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
