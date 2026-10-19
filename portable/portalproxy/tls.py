"""Keep verified HTTPS usable when a relocated macOS Python loses its CA path."""
import os
from pathlib import Path
import ssl
import sys


def verified_context():
    context = ssl.create_default_context()
    # Python.org/OpenSSL can refer to its old installation after bundling.
    # Use Apple's existing CA file only when no roots or explicit overrides
    # were loaded. Never disable certificate or hostname verification.
    if (sys.platform == 'darwin' and not os.environ.get('SSL_CERT_FILE')
            and not os.environ.get('SSL_CERT_DIR')
            and context.cert_store_stats()['x509_ca'] == 0
            and Path('/etc/ssl/cert.pem').is_file()):
        context.load_verify_locations(cafile='/etc/ssl/cert.pem')
    return context
