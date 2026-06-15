# Requirements Document

## Introduction

This feature adds a fully independent time-domain eddy-current analysis workflow to the existing project. The workflow has two sequential phases:

**Phase 1 (this spec):** A MATLAB GUI (`Time_domain_extraction_GUI.mlapp` or script-based `Time_domain_extraction_GUI.m`) that connects to a COMSOL LiveLink server, loads a `.mph` model, auto-detects studies and their associated solver IDs, and extracts time-domain B-field data at 7 canonical spatial measurement locations plus optional offset locations. Results are written to structured `.txt` files organised in 7 sub-folders mirroring the folder convention of the existing Python GUI.

**Phase 2 (future):** A Python GUI (`Time_domain_simulations_analysis_GUI.py`) that loads the extracted files and the processed measurement curves from the existing workflow, then compares them using the same 7-position philosophy as `main_gui.py`. Phase 2 is **out of scope** for this spec.

The existing `main_gui.py` and all files in the `analysis/` folder must remain **completely untouched**.

---

## Glossary

- **Extractor_GUI**: The MATLAB GUI application created by this feature (`Time_domain_extraction_GUI.m`).
- **COMSOL_Model**: A `.mph` file loaded via the COMSOL LiveLink MATLAB API (`mphload`).
- **Study**: A COMSOL study node (e.g., `std1`, `std2`). Each study has a human-readable label (e.g., "Reference", "AllPlates").
- **Reference_Study**: The mandatory study whose label is exactly "Reference". It provides the baseline solution used in the eddy-field subtraction expression.
- **Comparison_Study**: The user-selected study to compare against the Reference_Study.
- **Solution_ID**: The COMSOL solver tag associated with a study (e.g., `sol1`, `sol6`). Detected automatically; never hardcoded.
- **Measurement_Location**: One of the 7 canonical spatial points: Center (0,0,0), +X (+0.05,0,0), −X (−0.05,0,0), +Y (0,+0.05,0), −Y (0,−0.05,0), +Z (0,0,+0.05), −Z (0,0,−0.05). Coordinates are in metres.
- **Point_Dataset**: A COMSOL `CutPoint3D` dataset created programmatically for a single Measurement_Location.
- **Offset**: An additional displacement (mm, user-supplied) applied along one axis at a time to a Measurement_Location. Internally converted to metres before use.
- **Beddy_Expression**: The COMSOL expression `mf.By - withsol('<ref_sol_id>', mf.By, setval(t, t))` where `<ref_sol_id>` is the Solution_ID of the Reference_Study.
- **Time_Filter**: A threshold applied after extraction; only time samples satisfying `t >= threshold_s` are retained in the output file. The user enters the threshold in milliseconds; it is converted to seconds internally.
- **Output_Folder**: The user-selected root folder into which the Extractor_GUI writes one sub-folder per Measurement_Location.
- **Overwrite_Policy**: The session-scoped decision (Yes / No / Yes to All / No to All) governing whether existing output files are replaced.
- **Extraction_Session**: The lifetime of a single extraction run, from the moment the user clicks "Extract" until all files are written or the run is aborted.

---

## Requirements

### Requirement 1: COMSOL Server Connection and Model Loading

**User Story:** As a simulation engineer, I want to connect to a running COMSOL LiveLink server and load a `.mph` model file, so that I can access the model's studies and solutions programmatically.

#### Acceptance Criteria

1. THE Extractor_GUI SHALL provide a button that opens a file-browser dialog restricted to `.mph` files.
2. WHEN a valid `.mph` file path is selected, THE Extractor_GUI SHALL call `mphload` to load the COMSOL_Model into the MATLAB workspace.
3. WHEN `mphload` raises an error, THE Extractor_GUI SHALL display an error dialog containing the MATLAB error message and SHALL stop the loading sequence without crashing.
4. WHEN the COMSOL_Model is loaded successfully, THE Extractor_GUI SHALL display the model file name in a read-only text field.
5. THE Extractor_GUI SHALL attempt to start or connect to the COMSOL LiveLink server via `mphstart` before loading, and SHALL issue a non-fatal warning (not an error) if the server is already running.

---

### Requirement 2: Study Discovery and Reference Study Validation

**User Story:** As a simulation engineer, I want the GUI to automatically scan all studies in the loaded model and validate that a "Reference" study exists, so that I can be sure the extraction baseline is correctly identified before proceeding.

#### Acceptance Criteria

1. WHEN the COMSOL_Model is loaded successfully, THE Extractor_GUI SHALL enumerate all study nodes by calling `model.study.tags` and SHALL store both the study tag and its human-readable label.
2. WHEN the COMSOL_Model is loaded successfully, THE Extractor_GUI SHALL resolve the Solution_ID for each study by inspecting the study's solver sequence (e.g., via `model.study('<tag>').feature` or `model.sol.tags` cross-referencing), and SHALL store the (study_tag → solution_id) mapping.
3. WHEN no study with label "Reference" is found, THE Extractor_GUI SHALL display an error dialog with the text "No study labelled 'Reference' was found in the model. Extraction cannot proceed." and SHALL disable all subsequent workflow controls.
4. WHEN a study with label "Reference" is found, THE Extractor_GUI SHALL store its Solution_ID as the reference solution and SHALL display the detected Solution_ID in a read-only label (e.g., "Reference solution: sol1").
5. THE Extractor_GUI SHALL populate a drop-down list with all study labels discovered in step 1, so the user can select the Comparison_Study.
6. THE Extractor_GUI SHALL pre-select the first non-Reference study in the Comparison_Study drop-down as the default.

---

### Requirement 3: Comparison Study Selection

**User Story:** As a simulation engineer, I want to select which study to compare against the Reference, so that I can extract the differential eddy-field for any scenario (e.g., AllPlates, 2Plates).

#### Acceptance Criteria

1. THE Extractor_GUI SHALL display a labelled drop-down control populated with all available study labels from Requirement 2.
2. WHEN the user selects a study from the drop-down, THE Extractor_GUI SHALL update the internally stored Comparison_Study and its Solution_ID.
3. THE Extractor_GUI SHALL prevent the user from selecting the Reference_Study as the Comparison_Study, and SHALL either hide it from the drop-down or disable the "Extract" button when it is selected, with an explanatory tooltip or message.

---

### Requirement 4: Analysis Type Selection

**User Story:** As a simulation engineer, I want to choose the analysis geometry (Point or Cylinder), so that the correct dataset type is created in COMSOL for the extraction.

#### Acceptance Criteria

1. THE Extractor_GUI SHALL display two radio buttons or a drop-down labelled "Analysis Type" with options: "Point" and "Cylinder".
2. WHEN "Cylinder" is selected, THE Extractor_GUI SHALL disable all Cylinder-specific controls and SHALL display the label "(Not yet implemented)" adjacent to the Cylinder option.
3. THE Extractor_GUI SHALL default the Analysis Type selection to "Point" on startup.
4. WHEN "Point" is selected, THE Extractor_GUI SHALL enable the Point Analysis controls described in Requirements 5 and 6.

---

### Requirement 5: Offset Configuration for Point Analysis

**User Story:** As a simulation engineer, I want to optionally apply spatial offsets to the measurement locations, so that I can extract eddy-field profiles at positions displaced from the nominal measurement points.

#### Acceptance Criteria

1. THE Extractor_GUI SHALL display a checkbox labelled "Apply Offset?" that is unchecked by default.
2. WHEN "Apply Offset?" is unchecked, THE Extractor_GUI SHALL disable all offset input fields and SHALL extract only the nominal Measurement_Location points.
3. WHEN "Apply Offset?" is checked, THE Extractor_GUI SHALL enable three text input fields labelled "Offset X (mm)", "Offset Y (mm)", and "Offset Z (mm)".
4. WHEN an offset field contains a single numeric value (e.g., `10`), THE Extractor_GUI SHALL interpret it as a single offset of that magnitude in millimetres.
5. WHEN an offset field contains a comma-separated list (e.g., `10,20,30`), THE Extractor_GUI SHALL interpret it as multiple discrete offset values in millimetres.
6. THE Extractor_GUI SHALL convert all offset values from millimetres to metres before passing them to COMSOL (multiply by 0.001).
7. WHEN offsets are enabled, THE Extractor_GUI SHALL always include the nominal point (offset = 0) in the extraction set for each Measurement_Location, in addition to the user-specified offsets.
8. WHEN offsets are enabled, THE Extractor_GUI SHALL apply offsets one axis at a time: for X offsets, only `Point_offset_x` is non-zero; for Y offsets, only `Point_offset_y` is non-zero; for Z offsets, only `Point_offset_z` is non-zero.

---

### Requirement 6: Time Filter Configuration

**User Story:** As a simulation engineer, I want to filter the extracted time samples by a minimum time threshold, so that I can discard early transient samples before the solver reaches steady periodic behaviour.

#### Acceptance Criteria

1. THE Extractor_GUI SHALL display a text input field labelled "Filter Time (ms)" that accepts a threshold in milliseconds (e.g., `100.4`).
2. WHEN the filter field is empty or contains only whitespace, THE Extractor_GUI SHALL apply no time filtering and SHALL export all available time samples.
3. WHEN the filter field contains a valid numeric value `T_ms`, THE Extractor_GUI SHALL convert it to seconds as `T_s = T_ms / 1000` and SHALL retain only those time samples where `t >= T_s`.
4. WHEN the filter field contains a value that cannot be parsed as a positive number, THE Extractor_GUI SHALL display a validation error and SHALL prevent the extraction from starting.
5. THE Time_Filter SHALL be applied after data retrieval from COMSOL and before writing to disk.

---

### Requirement 7: COMSOL Point Dataset Creation

**User Story:** As a simulation engineer, I want the GUI to automatically create COMSOL `CutPoint3D` datasets for all 7 Measurement_Locations and their offset variants, so that I do not have to configure datasets manually in COMSOL.

#### Acceptance Criteria

1. WHEN the user initiates an extraction, THE Extractor_GUI SHALL create or reuse a `CutPoint3D` dataset in the COMSOL_Model for each of the 7 Measurement_Locations using coordinates defined in the Glossary.
2. THE Extractor_GUI SHALL name each Point_Dataset with a tag derived from the location name (e.g., `ptCenter`, `ptPlusX`, `ptMinusX`, `ptPlusY`, `ptMinusY`, `ptPlusZ`, `ptMinusZ`).
3. WHEN "Apply Offset?" is checked, THE Extractor_GUI SHALL set COMSOL model parameters `Point_offset_x`, `Point_offset_y`, and `Point_offset_z` to `'0'` as the baseline, then iterate over each offset axis and each offset value, updating only the relevant parameter while keeping the others at `'0'`.
4. WHEN a dataset tag already exists in the COMSOL_Model, THE Extractor_GUI SHALL reuse it rather than creating a duplicate.
5. THE Extractor_GUI SHALL assign the Comparison_Study's Solution_ID to each Point_Dataset before running an export.

---

### Requirement 8: Beddy Expression and Data Extraction

**User Story:** As a simulation engineer, I want the extraction to use the correct differential eddy-field expression referenced against the Reference_Study, so that the output files contain physically meaningful Beddy values.

#### Acceptance Criteria

1. THE Extractor_GUI SHALL use the expression `mf.By - withsol('<ref_sol_id>', mf.By, setval(t, t))` for all point data extractions, where `<ref_sol_id>` is the Solution_ID resolved from the Reference_Study in Requirement 2.
2. THE Extractor_GUI SHALL never hardcode a solution ID string (such as `'sol1'` or `'sol6'`); all solution IDs SHALL be resolved dynamically from the model at load time.
3. THE Extractor_GUI SHALL create a temporary `PlotGroup1D` and a `PointGraph` feature in the COMSOL_Model to evaluate the Beddy_Expression at each Point_Dataset.
4. THE Extractor_GUI SHALL set the export unit to `uT` (micro-Tesla) for all Beddy_Expression evaluations.
5. WHEN data retrieval from COMSOL returns an empty or all-NaN array for a given point, THE Extractor_GUI SHALL log a warning identifying the affected location and offset, and SHALL skip writing a file for that point.
6. THE Extractor_GUI SHALL minimise COMSOL re-computation by reusing existing solution data; it SHALL NOT trigger a full re-solve of any study unless no solution exists.

---

### Requirement 9: Output Folder and Sub-folder Creation

**User Story:** As a simulation engineer, I want the GUI to create a consistent folder structure under the chosen output directory, so that the Python analysis GUI can locate the extracted files without additional configuration.

#### Acceptance Criteria

1. THE Extractor_GUI SHALL display a button that opens a folder-browser dialog for selecting the Output_Folder.
2. WHEN the Output_Folder is selected, THE Extractor_GUI SHALL display the chosen path in a read-only text field.
3. WHEN extraction begins, THE Extractor_GUI SHALL create exactly 7 sub-folders inside the Output_Folder, named: `Center`, `+X`, `-X`, `+Y`, `-Y`, `+Z`, `-Z`.
4. IF a sub-folder already exists, THE Extractor_GUI SHALL reuse it without error.

---

### Requirement 10: Output File Naming Convention

**User Story:** As a simulation engineer, I want extracted files to follow a deterministic naming scheme, so that downstream scripts can find and parse them programmatically.

#### Acceptance Criteria

1. THE Extractor_GUI SHALL name the nominal-point output file (no offset) for a given Measurement_Location using the pattern: `BeddyTime_Point_<Location>.txt` (e.g., `BeddyTime_Point_Center.txt`, `BeddyTime_Point_+X.txt`).
2. THE Extractor_GUI SHALL name offset output files using the pattern: `BeddyTime_Point_<Location>_Offset<Axis>_<Value>mm.txt` where `<Axis>` is `X`, `Y`, or `Z`; and `<Value>` is the offset magnitude in millimetres as an integer if the value is whole, or as a decimal otherwise (e.g., `BeddyTime_Point_Center_OffsetX_10mm.txt`, `BeddyTime_Point_-Y_OffsetZ_5mm.txt`).
3. THE Extractor_GUI SHALL write each output file to the sub-folder corresponding to the Measurement_Location (e.g., the file for location `+X` is written inside the `+X` sub-folder).
4. THE output file SHALL contain two tab-separated columns: time (seconds) and Beddy (µT), with a one-line header `t_s\tBeddy_uT`.

---

### Requirement 11: Overwrite Handling

**User Story:** As a simulation engineer, I want to be asked before overwriting existing output files, with the option to apply my choice to all subsequent files in the session, so that I have control over which results are replaced.

#### Acceptance Criteria

1. WHEN an output file path already exists on disk and the Overwrite_Policy has not yet been set for the current Extraction_Session, THE Extractor_GUI SHALL display a modal dialog with the file name and four buttons: "Yes", "No", "Yes to All", "No to All".
2. WHEN the user selects "Yes to All", THE Extractor_GUI SHALL overwrite all subsequent existing files without prompting for the remainder of the Extraction_Session.
3. WHEN the user selects "No to All", THE Extractor_GUI SHALL skip all subsequent existing files without prompting for the remainder of the Extraction_Session.
4. WHEN the user selects "Yes", THE Extractor_GUI SHALL overwrite only the current file and SHALL continue to prompt for each subsequent existing file.
5. WHEN the user selects "No", THE Extractor_GUI SHALL skip only the current file and SHALL continue to prompt for each subsequent existing file.
6. THE Overwrite_Policy SHALL be reset to "unset" at the start of each new Extraction_Session.

---

### Requirement 12: Progress Feedback and Error Handling

**User Story:** As a simulation engineer, I want continuous progress feedback during extraction and clear error messages on failure, so that I can monitor long-running extractions and diagnose problems quickly.

#### Acceptance Criteria

1. THE Extractor_GUI SHALL display a progress indicator (e.g., status label or progress bar) that updates as each Measurement_Location and offset combination is processed.
2. THE Extractor_GUI SHALL log each completed file write to a scrollable log panel showing the file path and a success status.
3. WHEN an error occurs during extraction of a single location/offset, THE Extractor_GUI SHALL log the error with the MATLAB error message, SHALL continue to the next location/offset, and SHALL NOT abort the entire extraction session.
4. WHEN the full extraction session completes, THE Extractor_GUI SHALL display a summary dialog reporting: total files written, total files skipped (overwrite policy), and total errors encountered.
5. THE Extractor_GUI SHALL provide a "Cancel" button that, when clicked during an active extraction, SHALL stop the extraction after completing the current file write and SHALL display a cancellation confirmation.

---

### Requirement 13: Unit Conversion Correctness

**User Story:** As a simulation engineer, I want all unit conversions to be explicit and validated, so that output files contain physically correct values.

#### Acceptance Criteria

1. THE Extractor_GUI SHALL convert all user-supplied offset values from millimetres to metres by multiplying by `1e-3` before any COMSOL parameter assignment.
2. THE Extractor_GUI SHALL convert user-supplied time filter thresholds from milliseconds to seconds by dividing by `1000` before comparing against COMSOL time-axis values.
3. THE Extractor_GUI SHALL set the COMSOL export unit string to `'uT'` for all Beddy_Expression evaluations; it SHALL NOT apply any manual scaling factor to the retrieved values.
4. FOR ALL offset values provided by the user, THE Extractor_GUI SHALL verify that the converted value in metres is within the range [-1, 1] m and SHALL warn the user if a value falls outside this range.

---

### Requirement 14: Modular Code Architecture

**User Story:** As a developer, I want the MATLAB extraction code to be modular and well-documented, so that individual steps (model loading, dataset creation, extraction, file writing) can be tested and maintained independently.

#### Acceptance Criteria

1. THE Extractor_GUI SHALL separate the COMSOL interaction logic into helper functions distinct from the GUI callback functions (e.g., `load_model`, `detect_studies`, `create_point_datasets`, `extract_point_data`, `write_output_file`).
2. EACH helper function SHALL include a header comment documenting: its purpose, input arguments with types and units, output arguments with types and units, and any known COMSOL API constraints.
3. THE Extractor_GUI SHALL contain no hardcoded file paths to COMSOL installation directories; the COMSOL `mli` path SHALL be configurable via a dedicated input field or a stored preference, defaulting to the path used in `EDDY_CURRENT_B_EXTRACTOR.m` as a placeholder.
4. THE Extractor_GUI source file SHALL be named `Time_domain_extraction_GUI.m` and SHALL reside in the workspace root directory alongside `main_gui.py` and `EDDY_CURRENT_B_EXTRACTOR.m`.
