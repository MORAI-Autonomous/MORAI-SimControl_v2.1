from __future__ import annotations

from typing import Tuple, Union

EnumItems = Tuple[Tuple[int, str], ...]

ENTITY_TYPE_ITEMS: EnumItems = (
    (0, "ENTITY_TYPE_UNSPECIFIED"),
    (1, "ENTITY_TYPE_VEHICLE"),
    (2, "ENTITY_TYPE_PEDESTRIAN"),
    (3, "ENTITY_TYPE_OBSTACLE"),
    (4, "ENTITY_TYPE_ANIMAL"),
    (5, "ENTITY_TYPE_SENSOR"),
)

VEHICLE_DRIVING_MODE_ITEMS: EnumItems = (
    (0, "VEHICLE_DRIVING_MODE_UNSPECIFIED"),
    (1, "VEHICLE_DRIVING_MODE_DYNAMICS"),
    (2, "VEHICLE_DRIVING_MODE_KINEMATICS"),
)

GROUND_VEHICLE_MODEL_ITEMS: EnumItems = (
    (0, "GV_UNSPECIFIED"),
    (1, "GV_CAR_HD_IONIQ5_2023"),
    (2, "GV_CAR_HD_IONIQ5"),
    (3, "GV_CAR_HD_IONIQ6_2023"),
    (4, "GV_CAR_HD_STARIA_2021"),
    (5, "GV_CAR_HD_TUCSON_2022_CV"),
    (6, "GV_CAR_HD_SONATA_YF_2014"),
    (7, "GV_CAR_KA_NIRO_HEV_2017"),
    (8, "GV_CAR_KA_CARNIVAL_2020"),
    (9, "GV_CAR_KA_TORRESEVX_2024"),
    (10, "GV_CAR_MA_TCAR_2018_CV"),
    (11, "GV_CAR_MA_SEDAN_2025"),
    (12, "GV_CAR_MA_FORMULA4_2025"),
    (13, "GV_CAR_UN_KMRZR_2"),
    (14, "GV_CAR_UN_KMRZR_4"),
    (15, "GV_CAR_UN_K8SEDAN"),
    (16, "GV_CAR_UN_K8SUV"),
    (17, "GV_VAN_HD_STARIA_2021_AMBULANCE"),
    (18, "GV_VAN_UN_K8VAN"),
    (19, "GV_BUS_HD_CITYBUS_2023"),
    (20, "GV_BUS_HD_LOCALBUS_2023"),
    (21, "GV_BUS_OHMLIFT_2022"),
    (22, "GV_BUS_PXROBOBUS_2023"),
    (23, "GV_BUS_MASHUTTLEBUS"),
    (24, "GV_BUS_MABUS_2025_CV"),
    (25, "GV_BUS_UN_KK11SUTTLEBUS_2025"),
    (26, "GV_BUS_UN_K8LARGEBUS"),
    (27, "GV_TRK_KA_BONGO3EV_2025_SWEEPER"),
    (28, "GV_TRK_KA_BONGO3EV_2025_FUMIGATOR"),
    (29, "GV_TRK_KA_BONGO3EV_2025_DUSTVACUUM"),
    (30, "GV_TRK_KA_BONGO3EV_2025_MULTITRUCK"),
    (31, "GV_TRK_UN_KM923"),
    (32, "GV_TRK_UN_K8TRUCK_1TON"),
    (33, "GV_TRK_UN_K8TRUCK_15TON"),
    (34, "GV_TRK_UN_K8TRUCK_DUMP"),
    (35, "GV_TRL_UN_K8TRAILER"),
    (36, "GV_BIC_GTESCAPE"),
    (37, "GV_MTB_HNFURY"),
    (38, "GV_SP_HAAS21REDBACK"),
    (39, "GV_MIL_T72_TANK"),
    (40, "RV_WR_UN_KDILLYX3_2025"),
)


def enum_label(value: int, name: str) -> str:
    return f"{name} ({value})"


def enum_labels(items: EnumItems) -> list[str]:
    return [enum_label(value, name) for value, name in items]


def enum_label_for_value(items: EnumItems, value: int, default: int) -> str:
    for item_value, item_name in items:
        if item_value == value:
            return enum_label(item_value, item_name)
    return enum_label_for_value(items, default, default)


def enum_value_from_label(
    items: EnumItems,
    label: Union[str, int, float],
    default: int,
) -> int:
    if isinstance(label, (int, float)):
        return int(label)

    text = str(label).strip()
    if not text:
        return default

    for value, name in items:
        if text == name or text == enum_label(value, name):
            return value

    if text.endswith(")") and "(" in text:
        maybe_value = text.rsplit("(", 1)[1][:-1].strip()
        try:
            return int(maybe_value)
        except ValueError:
            pass

    try:
        return int(text)
    except ValueError:
        return default


def enum_options(items: EnumItems) -> dict[int, str]:
    return {value: name for value, name in items}
