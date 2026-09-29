from . import models
from . import controllers


def post_init_hook(env):
    """À l'installation : calcule l'accès extranet des droits déjà saisis."""
    env["coproerp.droit"]._cron_maj_acces_extranet()
