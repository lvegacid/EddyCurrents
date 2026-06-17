from pathlib import Path

# ==========================================================
# CONFIGURATION
# ==========================================================

ROOT_FOLDER = Path(
    r"Z:\Projects\EddyCurrents\Data_acquisition\Simulation results\COMSOL_Time_domain\OutWithoutBottomPlate\GX"
)

# ==========================================================
# DELETE OLD BACKUPS
# ==========================================================

deleted_backups = 0

for file in ROOT_FOLDER.rglob("*"):

    if file.is_file() and "backup" in file.name.lower():

        try:
            file.unlink()
            deleted_backups += 1
            print(f"[DELETED BACKUP] {file}")

        except Exception as e:
            print(f"[ERROR DELETING BACKUP] {file}")
            print(f"    {e}")

print(f"\nDeleted {deleted_backups} backup files.\n")

# ==========================================================
# INVERT SECOND COLUMN OF CYLINDER TXT FILES ONLY
# ==========================================================

processed = 0
failed = 0

for file in ROOT_FOLDER.rglob("*.txt"):

    # Process only files containing "Cylinder" in the filename
    if "cylinder" not in file.name.lower():
        continue

    try:

        lines = file.read_text(encoding="utf-8").splitlines()

        if not lines:
            print(f"[EMPTY FILE] {file}")
            continue

        output_lines = []

        # Preserve header exactly
        output_lines.append(lines[0])

        for line_number, line in enumerate(lines[1:], start=2):

            if not line.strip():
                continue

            parts = line.strip().split()

            if len(parts) < 2:
                print(
                    f"[WARNING] Invalid format in {file} "
                    f"(line {line_number}) -> {line}"
                )
                continue

            try:
                t_value = float(parts[0])
                b_value = float(parts[1])

                output_lines.append(
                    f"{t_value:.16g}\t{-b_value:.16g}"
                )

            except Exception:
                print(
                    f"[ERROR] Could not parse numeric values "
                    f"in file:\n{file}\n"
                    f"Line {line_number}: {line}\n"
                )
                raise

        file.write_text(
            "\n".join(output_lines),
            encoding="utf-8"
        )

        processed += 1
        print(f"[OK] {file}")

    except Exception as e:

        failed += 1

        print("\n" + "=" * 80)
        print("FAILED FILE")
        print(file)
        print(f"ERROR: {e}")
        print("=" * 80 + "\n")

# ==========================================================
# SUMMARY
# ==========================================================

print("\n")
print("=" * 80)
print("FINISHED")
print(f"Processed files : {processed}")
print(f"Failed files    : {failed}")
print("=" * 80)