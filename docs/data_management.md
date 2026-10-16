# Data management

How RS-CIA data is organised, from the files we receive to the model-ready rasters.

## Three stages, one set of themes

Every layer passes through three stages. Each stage uses the same thematic folders, so a layer
is always found in the same place.

| Stage | Folder | What it holds | Who writes it |
|---|---|---|---|
| Raw | `data/raw/` | Original files exactly as received, one folder per source, with a `SOURCE.md` note | People (download or receive) |
| Interim | `data/interim/` | Cleaned model inputs: clipped to the study area, reprojected, standard attribute names | Scripts |
| Processed | `data/processed/` | Model-ready 1 km rasters | `rscia` |

Raw files are never edited. Every change is made by a script that reads raw and writes interim,
so any layer can be rebuilt from its original files.

## Themes

Themes are set in `config/project.yaml` (`themes`). A component's `group` and a pressure's
`theme` decide its folder at every stage and how results are grouped in the summary tables.

| Part | Theme | Layers |
|---|---|---|
| Reference | boundaries | EEZ, MEOW regions, coastline |
| | bathymetry | GEBCO |
| | bio_oracle | Bio-ORACLE present and future layers |
| | surveys | 100 coral reef survey sites |
| Components | benthic_habitats | coral_shallow, coral_mesophotic, seagrass, mangrove, intertidal_flats, soft_sediment, hard_substrate, deep_sea |
| | marine_turtles | green_turtle, hawksbill_turtle, turtle_nesting |
| | marine_mammals | dugong, dolphins, other_cetaceans |
| | sharks_rays | whale_shark, manta_mobula |
| | seabirds | seabird_breeding, seabird_foraging |
| | fish | reef_fish, spawning_aggregations |
| | pelagic | pelagic_productive |
| Pressures | coastal_development | reclamation, dredging_sediment, light_pollution |
| | discharges | desal_brine, thermal_discharge, chemical_discharge, wastewater_nutrients |
| | maritime_transport | shipping_noise, ship_strike, oil_spill_risk |
| | fisheries_aquaculture | fishing_commercial, fishing_artisanal, aquaculture |
| | tourism | tourism_diving |
| | climate | marine_heatwaves, warming, acidification, deoxygenation, salinity_change |

## Folder tree

`rscia init-data` creates the full tree from the configuration and the catalogue. It never
overwrites existing files, so it is safe to run again after adding a layer.

```
data/
  raw/
    reference/   boundaries/<source>/  bathymetry/gebco/  bio_oracle/  surveys/
    components/  <theme>/<source>/              e.g. benthic_habitats/allen_coral_atlas/
    pressures/   <theme>/<source>/              e.g. discharges/desalination_plants/
    scenarios/   development/<pressure theme>/  applications/<application id>/
  interim/
    reference/   boundaries/  bathymetry/  bio_oracle/  surveys/
    components/  <theme>/
    pressures/   <theme>/                       files named in config/pressures.yaml (sources)
    scenarios/   development/<pressure theme>/  applications/<application id>/
  processed/
    grid/        template.tif, regions.tif
    components/  <theme>/<id>.tif               0 to 1
    pressures/   <theme>/<id>.tif               normalized 0 to 1
                 <theme>/intensity/<id>.tif     before normalization
                 references.json                normalization reference values
```

Raw folders are named after the source, not the layer, because one source often feeds several
layers. The Allen Coral Atlas feeds four benthic layers, AIS feeds two shipping pressures and the
desalination plant list feeds brine and chemical discharge.

## The data catalogue

`config/data_catalogue.csv` has one row per input layer and is the record of what we hold.

| Column | Content |
|---|---|
| layer_id, layer_type, theme, name | Identity, matching the configuration |
| source, url | Provider and where to get it |
| raw_folder | Folder for the original files |
| interim_path | Cleaned model input (file for pressures, folder for components) |
| processed_file | Model-ready raster |
| version, date_obtained, licence, owner | Fill in when the data arrives |
| status | `to_obtain`, `requested`, `raw`, `interim`, `processed`, `checked` (`to_load` for surveys) |
| data_confidence | 1 low, 2 medium, 3 high |
| notes | Method, weight field, caveats |

Move a layer's status forward as it passes each stage. `rscia check` reports missing inputs by
theme and flags catalogue rows that no longer match the configuration.

## Adding a layer, step by step

1. Put the files, unchanged, in its raw folder (`raw_folder` in the catalogue) and fill in
   `SOURCE.md` there. Set the catalogue status to `raw` and fill in version, date, licence and owner.
2. Clean it with a script that writes to `interim_path`: clip to the study area, reproject to
   the grid projection, use the attribute names in `config/pressures.yaml` (for example
   `capacity_m3_day`). Status `interim`.
3. Build the model-ready raster: `rscia prepare` for pressures; for components, write
   `processed_file` (0 to 1). Status `processed`.
4. Check it: quick-look map, value range, coverage, and the data confidence rating. Status `checked`.

## Shared storage

Data folders are not in git, apart from the README files. Keep one copy of the tree on the
team's shared storage and run `rscia init-data --data-root <shared folder>` once to create it.
Each user then replaces the repository's `data/` folder, which only holds README files, with a
link to the shared copy. From the repository folder:

- Windows (Command Prompt): `rmdir /S /Q data` then `mklink /D data \\server\share\rscia\data`
- macOS or Linux: `rm -r data` then `ln -s /path/to/shared/rscia/data data`

Copy the three stage README files to the shared copy first, so they travel with the data.

## Order of work

1. Reference layers and grid: EEZ, coastline, MEOW (set the split latitude), GEBCO, then
   `rscia build-grid`.
2. National data requests, early: desalination plants and capacities, outfalls, ports and
   dredging, reclamation, planned developments, turtle nesting, dugong surveys, landing sites.
3. Open global data: Allen Coral Atlas, Global Mangrove Watch, tidal flats, Bio-ORACLE,
   Coral Reef Watch, VIIRS, Global Fishing Watch, OBIS and GBIF.
4. Coral survey sites: `scripts/import_coral_surveys.py`.
5. `rscia check` weekly.
