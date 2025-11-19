from enum import Enum

class AdminLevel(str, Enum):
    REGION = "region"
    DEPARTEMENT = "departement"
    COMMUNE = "commune"
    ARRONDISSEMENT = "arrondissement"


ADMIN_LEVELS_HIERARCHY = {
    "region": 1,
    "departement": 2,
    "commune": 3,
    "arrondissement": 4,
}