"""Route modules for the shared ``api`` blueprint.

Importing this package registers every route module on the blueprint as an
import side effect; core.api's create_app() imports it before
register_blueprint(api). Route modules import shared plumbing from
core.api_infra — never from core.api (that would be circular).
"""
from core.routes import (  # noqa: F401
    auth,
    detections,
    images,
    media,
    migration,
    observations,
    settings,
    species,
    system,
)
