# Data

Monday instance, CSV only: `csv/ie7200_Mon_*.csv`

| File | Contents |
|---|---|
| `distance` | 35x35 distance matrix (miles); row/col 0 = depot |
| `locations` | Per-location: depot flag, distance from depot, order count, total volume |
| `orders` | 43 orders: location, volume (ft³), unload time (min) |
| `parameters` | Capacities, speed, unload rates, DOT limits, delivery window, dock waves |
| `vehicle_types` | Per-order vehicle eligibility (Van, or Straight Truck only) |
