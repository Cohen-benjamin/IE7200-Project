"""Problem parameters: Params and VehicleType dataclasses.

All numeric values are read from ``parameters.csv``; nothing is hard-coded here.
Units used throughout: miles, minutes, ft3.
"""
# Lets us write type hints like ``tuple[VehicleType, ...]`` and refer to a class
# inside its own definition without quoting it.
from __future__ import annotations

# ``dataclass`` auto-writes __init__/__repr__ for classes that are mostly data.
from dataclasses import dataclass
# ``Path`` is the standard object for file paths (works on Windows and Linux).
from pathlib import Path

# pandas reads the CSV into a table (DataFrame/Series) we can look values up in.
import pandas as pd

# Unit conversion (not a model parameter): minutes in one hour.
# Used to turn "miles per hour" into "minutes per mile": 60 / mph.
MIN_PER_HOUR = 60

# Label for the homogeneous M1 fleet. A name, not a number, so it is allowed here.
VAN_NAME = "Van"


# frozen=True: after creation, fields cannot be reassigned (inst.capacity_ft3 = 1
# raises an error). Stops any solver from silently changing a shared limit.
@dataclass(frozen=True)
class VehicleType:
    """One vehicle class.

    Attributes:
        name: label, e.g. "Van".
        capacity_ft3: max total order volume on one route (ft3).
        unload_min_per_ft3: unload rate above the floor (min/ft3).
        min_unload_min: floor on unload time charged per order (min).
    """

    # Field declarations: dataclass turns these into __init__ arguments, in order.
    name: str
    capacity_ft3: float
    unload_min_per_ft3: float
    min_unload_min: float

    def unload_time_min(self, volume_ft3: float) -> float:
        """Unload time for ONE order.

        Inputs:
            volume_ft3: order volume (ft3).
        Output:
            minutes = max(min_unload_min, unload_min_per_ft3 * volume_ft3).
        Note: paid per order, so a stop with k orders sums k of these.
        """
        # rate * volume is the "real" unload time; max() applies the per-order
        # floor so small orders still cost the minimum (e.g. 30 min).
        # ``self`` = the VehicleType this method is called on (the van's own
        # rate and floor are used, which is why this is a method).
        return max(self.min_unload_min, self.unload_min_per_ft3 * volume_ft3)


@dataclass(frozen=True)
class Params:
    """Route-level limits and fleet definition.

    Attributes:
        drive_min_per_mile: driving time per mile (min/mi) = 60 / speed (mph).
        max_drive_min: cap on total driving per route, depot legs included (min).
        max_duty_min: cap on driving + unloading per route (min).
        window_start_min: earliest delivery start, minutes after midnight.
        window_end_min: latest delivery completion, minutes after midnight.
        vehicle_types: available vehicle classes (M1: Van only).
    """

    drive_min_per_mile: float
    max_drive_min: float
    max_duty_min: float
    window_start_min: float
    window_end_min: float
    # A tuple (immutable) rather than a list, so the fleet list can't be edited.
    # ``tuple[VehicleType, ...]`` = "any number of VehicleType objects".
    vehicle_types: tuple[VehicleType, ...]

    # @property: used like an attribute (params.max_span_min), not a call.
    # It is computed on demand, so it can never disagree with the window fields.
    @property
    def max_span_min(self) -> float:
        """Cap on span (inter-stop drive + all unload), in minutes.

        Equals the delivery-window length: window_end_min - window_start_min.
        """
        # Window is 480 -> 1080 (08:00 -> 18:00), so the span cap is 600 min.
        return self.window_end_min - self.window_start_min

    def vehicle(self, name: str) -> VehicleType:
        """Look up a vehicle type by name.

        Inputs:
            name: vehicle label, e.g. "Van".
        Output:
            the matching VehicleType. Raises KeyError if the name is unknown.
        """
        # Linear scan: the fleet has 1-2 types, so a dict would be overkill.
        for vt in self.vehicle_types:
            if vt.name == name:
                return vt
        # Reached only if no type matched. Fail loudly instead of returning None,
        # so a typo can't silently turn into "no vehicle".
        # {name!r} prints the name with quotes, which makes typos visible.
        raise KeyError(f"unknown vehicle type: {name!r}")


def load_params(parameters_csv: Path) -> Params:
    """Build Params from ``parameters.csv`` (columns: Parameter, Value, ...).

    Inputs:
        parameters_csv: path to the parameters CSV.
    Output:
        Params with a single Van vehicle type (M1). Dock-wave and Straight
        Truck rows are ignored (Milestone 2).
    Units: speed mph -> drive_min_per_mile (min/mi); the rest as in the CSV.
    """
    # Read the CSV, make the "Parameter" column the row label, and keep only the
    # "Value" column. Result: a lookup like table["SpeedMPH"] -> 40.
    table = pd.read_csv(parameters_csv).set_index("Parameter")["Value"]

    # Small helper defined inside load_params so it can see ``table``.
    def val(key: str) -> float:
        """Numeric value of one CSV row (raises KeyError if the row is missing)."""
        # float() because the Value column may be read as text/int; a missing
        # row raises KeyError, which flags a malformed parameters file.
        return float(table[key])

    # Build the Van from the CSV rows that describe it. Keyword arguments make
    # it obvious which CSV row feeds which field.
    van = VehicleType(
        name=VAN_NAME,
        capacity_ft3=val("VehicleCapacity"),          # ft3
        unload_min_per_ft3=val("UnloadRateMinPerFt3"),  # min/ft3
        min_unload_min=val("MinUnloadTimeMin"),       # min per order
    )
    return Params(
        # 60 min/hr divided by mph gives min/mi (40 mph -> 1.5 min/mi).
        drive_min_per_mile=MIN_PER_HOUR / val("SpeedMPH"),
        max_drive_min=val("MaxDriveTimeMin"),          # DOT driving cap
        max_duty_min=val("MaxDutyTimeMin"),            # DOT drive + unload cap
        window_start_min=val("DeliveryWindowOpenMin"),   # minutes after midnight
        window_end_min=val("DeliveryWindowCloseMin"),    # minutes after midnight
        # One-element tuple: the trailing comma is what makes it a tuple.
        vehicle_types=(van,),
    )
