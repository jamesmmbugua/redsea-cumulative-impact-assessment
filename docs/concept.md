# Concept: Red Sea Cumulative Impact Assessment

Version 0.1, October 2026

## 1. Purpose

Provide a transparent, repeatable way to map the combined impact of human activities and
climate change on marine ecosystems in the Saudi Red Sea EEZ, and to compare planning
scenarios against the current situation.

Two uses:

- **Baseline impact mapping:** current cumulative impact, hotspots, and which pressures and
  ecosystem components drive it.
- **Scenario comparison:** change in impact from planned developments, future climate, or both.

## 2. Study area and grid

| Item | Decision |
|---|---|
| Area | Saudi Arabian EEZ in the Red Sea, including the Saudi side of the Gulf of Aqaba. The Arabian Gulf EEZ is excluded. |
| Boundary source | Marine Regions (VLIZ) EEZ dataset. Some boundaries are not formally delimited; treat as indicative. |
| Coastal strip | 2 km landward buffer so mangroves, intertidal flats and nesting beaches are included. |
| Resolution | 1 km x 1 km |
| Projection | Albers Equal Area centred on the Saudi Red Sea (lat_0 22, lon_0 39, standard parallels 18.5 and 27.5). Equal-area cells keep impacts comparable along the whole coast. |

## 3. Ecosystem components (21)

Each component is a 0 to 1 raster of presence (habitats) or relative importance (species).
The group is also the component's data folder (see `docs/data_management.md`).

| ID | Component | Group |
|---|---|---|
| coral_shallow | Shallow coral reef (0 to 30 m) | Benthic habitats |
| coral_mesophotic | Mesophotic coral (30 to 150 m) | Benthic habitats |
| seagrass | Seagrass beds | Benthic habitats |
| mangrove | Mangroves | Benthic habitats |
| intertidal_flats | Intertidal flats | Benthic habitats |
| soft_sediment | Subtidal soft sediment | Benthic habitats |
| hard_substrate | Non-reef hard substrate | Benthic habitats |
| deep_sea | Deep-sea habitats (below 200 m) | Benthic habitats |
| dugong | Dugong | Marine mammals |
| green_turtle | Green turtle (foraging) | Marine turtles |
| hawksbill_turtle | Hawksbill turtle (foraging) | Marine turtles |
| turtle_nesting | Turtle nesting beaches | Marine turtles |
| whale_shark | Whale shark | Sharks and rays |
| manta_mobula | Manta and mobula rays | Sharks and rays |
| dolphins | Dolphins (coastal and oceanic) | Marine mammals |
| other_cetaceans | Other cetaceans | Marine mammals |
| seabird_breeding | Seabird breeding islands | Seabirds |
| seabird_foraging | Seabird foraging areas | Seabirds |
| reef_fish | Reef fish assemblages | Fish |
| spawning_aggregations | Fish spawning aggregation sites | Fish |
| pelagic_productive | Productive pelagic waters | Pelagic |

## 4. Pressures (19)

Each pressure is a 0 to 1 raster of intensity.

| ID | Pressure | Proxy | Spatial model |
|---|---|---|---|
| desal_brine | Hypersaline brine | Desalination plants, capacity | Distance decay from outfall |
| thermal_discharge | Thermal discharge | Power and desalination outfalls | Distance decay |
| chemical_discharge | Antiscalants, chlorine, metals | Desalination outfalls | Distance decay |
| reclamation | Reclamation and habitat loss | Reclaimed and built coastline | Footprint |
| dredging_sediment | Dredging and sedimentation | Ports, channels, construction | Distance decay |
| wastewater_nutrients | Wastewater and nutrients | Treatment outfalls, coastal population | Distance decay |
| shipping_noise | Underwater noise | AIS vessel density | Density surface |
| ship_strike | Collision risk | AIS density weighted by speed | Density surface |
| oil_spill_risk | Oil spill risk | Lanes, terminals, platforms | Density plus decay |
| fishing_commercial | Commercial fishing | Global Fishing Watch effort | Density surface |
| fishing_artisanal | Artisanal fishing | Landing sites, coastal population | Distance decay |
| aquaculture | Aquaculture effluent | Farms, production | Distance decay |
| tourism_diving | Tourism and diving | Dive sites, resorts, marinas | Distance decay |
| light_pollution | Artificial light at night | VIIRS night lights | Direct |
| marine_heatwaves | Marine heatwaves | NOAA Coral Reef Watch DHW frequency | Direct, resampled |
| warming | Long-term warming | Bio-ORACLE temperature change | Climate delta |
| acidification | Ocean acidification | Bio-ORACLE pH change | Climate delta |
| deoxygenation | Oxygen loss | Bio-ORACLE oxygen change | Climate delta |
| salinity_change | Salinity change | Bio-ORACLE salinity change | Climate delta |

Distance decay uses `intensity = weight x exp(-distance / decay_km)` summed over sources,
with a cutoff at three times `decay_km`. Distances are straight-line in version 1; around-land
(marine) distances are a planned improvement.

## 5. Normalization

1. Optional log transform (`log1p`) for strongly skewed layers (shipping, fishing, population).
2. Scale to the 99th percentile of the baseline layer, then clip to 0 to 1.
3. Scenario layers are scaled with the **baseline** reference value. A scenario layer is the
   baseline layer plus the change on that same scale, so unchanged cells are identical to the
   baseline and an increase above today's maximum stays visible (values can exceed 1).
4. Climate deltas are scaled to the largest projected change (SSP5-8.5, 2100), so all
   climate futures share one scale.

## 6. Sensitivity matrix

- 19 pressures x 21 components, scores 0 to 1 (0 = no effect, 1 = severe and long-lasting).
- Seeded from literature and existing matrices (Symphony, Halpern et al., Tools4MSP),
  then refined in an expert workshop.
- Each score has a confidence rating (1 low, 2 medium, 3 high) in a parallel file.
- The template in `config/sensitivity_matrix.csv` is a placeholder for testing only and must
  be replaced before results are used.

## 7. Model

```
Impact(cell) = sum_p sum_c  P_p(cell) x E_c(cell) x S_pc
```

Also produced per run:

- Impact by pressure (sum over components)
- Impact by component (sum over pressures)
- Number of components present per cell (to separate "many ecosystems" from "high pressure")
- Confidence layer combining input data quality and sensitivity confidence

Planned extension: an optional interaction term for heat stress combined with local
pollution on corals, tested against survey data.

## 8. Coral reef survey data (100 sites)

The survey sites are used in three ways, in this priority:

1. **Validation (primary).** Compare modelled impact at each site with observed condition
   (live coral cover, recent mortality, bleaching, macroalgae, fish biomass) using rank
   correlation. A clear negative relationship between impact and coral cover supports the model.
2. **Sensitivity review.** Sites with high impact but good condition, or the reverse, point to
   sensitivity scores or pressure layers that need revisiting.
3. **Coral layer ground truth.** Check the coral habitat layer (Allen Coral Atlas) against
   surveyed reef locations.

To avoid circular reasoning, survey condition is **not** used to weight the coral component
in the same model run that it validates. If condition weighting is wanted later, hold out a
subset of sites for validation.

## 9. Climate data (Bio-ORACLE v3 and NOAA Coral Reef Watch)

- Bio-ORACLE present-day and future layers for surface and benthic temperature, pH,
  dissolved oxygen and salinity.
- Climate pressure = projected change from present (warming, pH decrease, oxygen decrease,
  absolute salinity change).
- Bio-ORACLE is about 0.05 degrees (roughly 5 km), resampled bilinearly to 1 km. Results
  should not be read as 1 km climate detail.
- Bio-ORACLE gives long-term means, not events, so marine heatwave stress comes from NOAA
  Coral Reef Watch Degree Heating Weeks.
- Bio-ORACLE environmental layers (temperature, salinity, light at bottom, currents,
  chlorophyll, depth) can also drive habitat suitability models for data-poor components
  such as seagrass, mesophotic coral and dugong.

## 10. Scenarios

| ID | Pressures | Climate | Runs |
|---|---|---|---|
| S0_baseline | Current | Present | 1 |
| S1_development | Current plus planned projects | Present | 1 |
| S2_climate | Current | SSP1-2.6, SSP2-4.5, SSP5-8.5 at 2050 and 2100 | 6 |
| S3_combined | Current plus planned projects | SSP1-2.6, SSP2-4.5, SSP5-8.5 at 2050 and 2100 | 6 |

Total: 14 runs. Time horizons are the 2040s and 2090s decades in Bio-ORACLE, labelled 2050
and 2100. Each run produces an impact map, a difference map against S0, and summary tables.

Planned projects are entered as point, line or polygon features (for example a new
desalination plant with capacity, a port, a reclamation footprint) and converted into
pressure layers with the same rules as the baseline.

## 11. Outputs

- Cumulative impact maps (total and per component group)
- Hotspot maps (top 10 percent of cells)
- Contribution breakdowns by pressure and component, for the whole EEZ and per planning unit
- Scenario difference maps
- Confidence maps
- Validation report against coral survey sites

## 12. Known limitations

- Additive model: no synergies or antagonisms in version 1.
- Sensitivity scores rely on expert judgement.
- Data gaps for some species and for artisanal fishing.
- Straight-line distance decay can leak pressure across headlands and islands.
- Climate layers are coarser than the grid.
