# Implementation Plan: Time-Domain COMSOL Extractor GUI

## Overview

Implement `Time_domain_extraction_GUI.m` as a MATLAB script-based GUI (uifigure) in the workspace root. The script connects to a COMSOL LiveLink server, loads a `.mph` model, auto-detects studies and solution IDs, and extracts time-domain Beddy (differential eddy-field) data at 7 canonical measurement locations with optional spatial offsets. Results are written to structured `.txt` files organised in 7 sub-folders.

## Tasks

- [x] 1. Scaffold the script file and define all helper function signatures
  - Create `Time_domain_extraction_GUI.m` in the workspace root with the top-level script entry point and empty stub functions: `load_model`, `detect_studies`, `create_point_datasets`, `extract_point_data`, `write_output_file`, `apply_time_filter`, `format_offset_value`, `resolve_sol_id`
  - Each stub must include a header comment block: purpose, input arguments (name / type / unit), output arguments (name / type / unit), known COMSOL API constraints
  - Add the `addpath` call for the COMSOL `mli` directory using a configurable variable (defaulting to the path in `EDDY_CURRENT_B_EXTRACTOR.m`): `/home/Comsol/Comsol/comsol64/multiphysics/mli`
  - _Requirements: 14.1, 14.2, 14.3, 14.4_

- [x] 2. Build the uifigure layout and static UI controls
  - [x] 2.1 Create the main uifigure with a grid layout containing all control groups
    - COMSOL `mli` path field (editable, pre-filled with default) + "Connect" button
    - Model file path field (read-only) + "Browse Model" button
    - Reference solution label (read-only, e.g. "Reference solution: –")
    - Comparison study drop-down (empty until model loaded)
    - Analysis Type radio group: "Point" (default) / "Cylinder (Not yet implemented)"
    - "Apply Offset?" checkbox (unchecked by default) + three offset text fields: "Offset X (mm)", "Offset Y (mm)", "Offset Z (mm)" (disabled by default)
    - "Filter Time (ms)" text field
    - Output folder path field (read-only) + "Browse Output" button
    - Scrollable log text area
    - Progress label + "Extract" button + "Cancel" button
    - _Requirements: 1.1, 1.4, 2.4, 2.5, 3.1, 4.1, 4.2, 4.3, 5.1, 5.3, 6.1, 9.1, 9.2, 12.1, 12.2, 12.5_

  - [x] 2.2 Wire UI control enable/disable logic
    - "Apply Offset?" checkbox toggles offset fields enabled/disabled (Req 5.2, 5.3)
    - Analysis Type radio disables Extract button and shows "(Not yet implemented)" when "Cylinder" selected (Req 4.2)
    - All extraction controls disabled until model is loaded successfully (Req 1.2, 2.3)
    - _Requirements: 4.2, 4.4, 5.2, 5.3_

- [x] 3. Implement COMSOL server connection and model loading (`load_model`)
  - [x] 3.1 Implement the "Connect & Load" sequence in the "Browse Model" callback
    - Call `mphstart` inside try/catch; issue `warning(...)` (non-fatal) if already connected (Req 1.5)
    - Open `uigetfile('*.mph')` file browser (Req 1.1)
    - Call `mphload(modelPath)` and catch any error, showing `uierrordlg` with the MATLAB error message (Req 1.2, 1.3)
    - On success, display the file name in the read-only field (Req 1.4)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 3.2 Write unit tests for `load_model` error paths
    - Test that a missing file path produces an error dialog string (mock `mphload`)
    - Test that a successful load returns a non-empty model handle
    - _Requirements: 1.2, 1.3_

- [x] 4. Implement study discovery and Reference study validation (`detect_studies`, `resolve_sol_id`)
  - [x] 4.1 Implement `detect_studies(model)` → returns struct array with fields `tag`, `label`, `sol_id`
    - Enumerate `model.study.tags`; for each tag get label via `model.study(tag).label`
    - Implement `resolve_sol_id(model, studyTag)`: cross-reference `model.sol.tags` to find the solver whose study attribute matches `studyTag`; fall back to iterating study features for a `'Stationary'`/`'Transient'` solver feature that links a `sol` tag
    - Never hardcode any solution ID string (Req 2.2, 8.2)
    - _Requirements: 2.1, 2.2, 8.2_

  - [x] 4.2 Implement Reference study validation and UI population after model load
    - Search for a study with `label == 'Reference'`; if not found show `uierrordlg` with exact message from Req 2.3 and disable extraction controls (Req 2.3)
    - Store `ref_sol_id` in app state; display "Reference solution: <sol_id>" in read-only label (Req 2.4)
    - Populate comparison drop-down with all study labels; exclude the Reference study (Req 2.5, 3.3)
    - Pre-select the first non-Reference study (Req 2.6)
    - _Requirements: 2.3, 2.4, 2.5, 2.6, 3.3_

  - [x] 4.3 Write property test for solution ID resolution
    - **Property 1: resolve_sol_id never returns a hardcoded string literal**
    - **Validates: Requirements 2.2, 8.2**
    - For a generated mock study/sol tag table, verify that the resolved ID always matches the dynamically derived mapping, never a literal like `'sol1'`
    - _Requirements: 2.2, 8.2_

- [x] 5. Implement COMSOL CutPoint3D dataset creation (`create_point_datasets`)
  - [x] 5.1 Implement `create_point_datasets(model, comp_sol_id)` for the 7 canonical locations
    - Locations and tags: Center(0,0,0)→`ptCenter`, +X(0.05,0,0)→`ptPlusX`, -X(-0.05,0,0)→`ptMinusX`, +Y(0,0.05,0)→`ptPlusY`, -Y(0,-0.05,0)→`ptMinusY`, +Z(0,0,0.05)→`ptPlusZ`, -Z(0,0,-0.05)→`ptMinusZ`
    - Check existing dataset tags; create only if tag absent (Req 7.4)
    - Set `dataset.set('solution', comp_sol_id)` for each point dataset (Req 7.5)
    - _Requirements: 7.1, 7.2, 7.4, 7.5_

  - [x] 5.2 Write unit tests for `create_point_datasets`
    - Test that all 7 tags are created when absent
    - Test that existing tags are reused (no duplicate creation)
    - _Requirements: 7.1, 7.2, 7.4_

- [-] 6. Implement offset parameter handling and unit conversion
  - [x] 6.1 Implement offset value parsing in the Extract callback
    - Parse each offset field: single value or comma-separated list → numeric vector in mm
    - Show validation `uierrordlg` for non-numeric entries; block extraction (Req 6.4 analogue for offsets)
    - Convert mm → m by multiplying by `1e-3` (Req 13.1)
    - Validate that each converted value is in `[-1, 1]` m; issue `uiconfirm` warning if outside range (Req 13.4)
    - _Requirements: 5.4, 5.5, 5.6, 13.1, 13.4_

  - [ ] 6.2 Implement `format_offset_value(val_mm)` → string for filename
    - Return integer string (e.g. `'10'`) if `val_mm` is a whole number, decimal string otherwise (e.g. `'5.5'`)
    - _Requirements: 10.2_

  - [ ] 6.3 Write property test for `format_offset_value`
    - **Property 2: format_offset_value(v) for whole-number v returns a string with no decimal point**
    - **Validates: Requirements 10.2**
    - Generate random integer-valued offsets; assert no `'.'` in result
    - _Requirements: 10.2_

- [ ] 7. Implement time filter configuration and validation (`apply_time_filter`)
  - [ ] 7.1 Implement `apply_time_filter(t_vec, data_vec, filter_ms)` → `[t_out, data_out]`
    - If `filter_ms` is empty/whitespace, return full vectors (Req 6.2)
    - Convert `filter_ms / 1000` → `T_s`; retain only indices where `t_vec >= T_s` (Req 6.3, 13.2)
    - Raise error string for non-positive or non-numeric `filter_ms` (Req 6.4)
    - _Requirements: 6.2, 6.3, 6.4, 13.2_

  - [ ] 7.2 Write property test for `apply_time_filter`
    - **Property 3: apply_time_filter output contains only t values >= threshold**
    - **Validates: Requirements 6.3, 13.2**
    - For arbitrary time vectors and thresholds, assert `all(t_out >= T_s)`
    - _Requirements: 6.3, 13.2_

- [ ] 8. Implement Beddy expression data extraction (`extract_point_data`)
  - [ ] 8.1 Implement `extract_point_data(model, pt_tag, ref_sol_id, comp_sol_id)` → `[t_vec, beddy_uT]`
    - Build expression string: `['mf.By - withsol(''' ref_sol_id ''', mf.By, setval(t, t))']` (Req 8.1, 8.2)
    - Create or reuse a `PlotGroup1D` (tag `pgTimeDomain`) and `PointGraph` feature (tag `ptgr1`) in the model result tree (Req 8.3)
    - Set `expr` to the Beddy expression, `unit` to `'uT'`, `data` to `pt_tag`, and `solrepresentation` / `sol` to `comp_sol_id` (Req 8.4)
    - Evaluate via `mpheval` or by running the plot group and reading data; do NOT call `model.study.run` (Req 8.6)
    - If result is empty or all-NaN: log a warning with location/offset info and return empty (Req 8.5)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [ ] 8.2 Write unit tests for `extract_point_data` guard conditions
    - Test empty-result branch returns `[]` and logs warning string
    - Test all-NaN branch returns `[]`
    - _Requirements: 8.5_

- [ ] 9. Implement output folder creation and file writing (`write_output_file`)
  - [ ] 9.1 Implement sub-folder creation for all 7 locations
    - Sub-folder names: `Center`, `+X`, `-X`, `+Y`, `-Y`, `+Z`, `-Z` (Req 9.3)
    - Use `mkdir` idempotently; do not error if folder exists (Req 9.4)
    - _Requirements: 9.3, 9.4_

  - [ ] 9.2 Implement `write_output_file(out_folder, location, axis, val_mm, t_vec, beddy_uT)` → file path
    - Build filename: nominal → `BeddyTime_Point_<Location>.txt`; offset → `BeddyTime_Point_<Location>_Offset<Axis>_<Value>mm.txt` (Req 10.1, 10.2)
    - Write to `<out_folder>/<location>/<filename>`; two tab-separated columns with header `t_s\tBeddy_uT` (Req 10.3, 10.4)
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [ ] 9.3 Write property test for filename generation
    - **Property 4: Nominal filename contains no 'Offset' substring; offset filename encodes axis and value**
    - **Validates: Requirements 10.1, 10.2**
    - Generate arbitrary location/axis/value combinations; assert naming invariants hold
    - _Requirements: 10.1, 10.2_

- [ ] 10. Implement overwrite policy dialog and session state
  - Implement session-scoped `overwrite_policy` variable (reset to `'unset'` at start of each extraction run) (Req 11.6)
  - Before each file write, check if file exists; if yes and policy is `'unset'`, show modal `uiconfirm` with four buttons: "Yes", "No", "Yes to All", "No to All" (Req 11.1)
  - Apply policy transitions per Req 11.2–11.5
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

- [ ] 11. Implement the main extraction loop with progress feedback and cancellation
  - [ ] 11.1 Implement the `Extract` button callback orchestrating the full extraction loop
    - Validate output folder and time filter field before starting; show `uierrordlg` and abort on invalid input (Req 6.4)
    - Reset `overwrite_policy` to `'unset'` (Req 11.6)
    - Set comparison study's `sol_id` on all 7 point datasets (Req 7.5)
    - Outer loop: 7 locations × inner loop: nominal point + each offset combination per axis (Req 5.7, 5.8)
    - For each (location, offset): set COMSOL parameters `Point_offset_x/y/z` via `model.param.set` (Req 7.3); call `extract_point_data`; call `apply_time_filter`; call `write_output_file` with overwrite check
    - After each file: update progress label and append to log text area (Req 12.1, 12.2)
    - Catch per-location errors, log with MATLAB message, continue (Req 12.3)
    - After loop: show summary `uialert` with total written / skipped / errors (Req 12.4)
    - _Requirements: 5.7, 5.8, 7.3, 12.1, 12.2, 12.3, 12.4_

  - [ ] 11.2 Implement the `Cancel` button callback
    - Set a shared `cancel_requested` flag that the extraction loop checks after each file write
    - When triggered, finish the current file write, then stop; show cancellation confirmation (Req 12.5)
    - _Requirements: 12.5_

- [ ] 12. Checkpoint — Ensure all helper functions integrate end-to-end
  - Wire `detect_studies` output into comparison drop-down population and `ref_sol_id` storage
  - Wire `create_point_datasets` call at extraction start
  - Verify COMSOL parameter reset to `'0'` after each axis loop (Req 7.3)
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 2.1, 2.2, 7.3_

- [ ] 13. Final validation and unit conversion audit
  - [ ] 13.1 Audit every COMSOL parameter assignment to confirm mm→m conversion (`* 1e-3`) is applied (Req 13.1)
  - [ ] 13.2 Audit every time-filter comparison to confirm ms→s conversion (`/ 1000`) is applied (Req 13.2)
  - [ ] 13.3 Confirm `unit` is set to `'uT'` in every `extract_point_data` call and no manual scaling factor is applied (Req 13.3)
  - [ ] 13.4 Confirm the `[-1, 1]` m range check is present for all offset values (Req 13.4)
  - _Requirements: 13.1, 13.2, 13.3, 13.4_

- [ ] 14. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- The output file is a single MATLAB script `Time_domain_extraction_GUI.m`; do NOT modify `main_gui.py`, `EDDY_CURRENT_B_EXTRACTOR.m`, or anything in `analysis/`
- All solution IDs must be resolved dynamically at model load time — never hardcoded
- The COMSOL `mli` path is configurable via a UI field; default matches `EDDY_CURRENT_B_EXTRACTOR.m`
- Property tests validate universal correctness properties; unit tests validate specific examples and edge cases
- Checkpoints ensure incremental validation after key integration points
