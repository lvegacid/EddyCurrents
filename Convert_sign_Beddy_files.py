from pathlib import Path

# ==========================================
# Root folder
# ==========================================
ROOT_FOLDER = r"Z:\Projects\EddyCurrents\Data_acquisition\Simulation results\COMSOL_Time_domain\OutWithoutBottomPlateAndInternalshielding\GX\To_be_converted"   # <-- Change this

root = Path(ROOT_FOLDER)

processed_files = 0

for subfolder in sorted([p for p in root.iterdir() if p.is_dir()]):

    txt_files = sorted(subfolder.rglob("*.txt"))

    for txt in txt_files:
        try:
            with txt.open("r", encoding="utf-8") as f:
                lines = f.readlines()

            new_lines = []

            for line in lines:

                stripped = line.strip()

                if not stripped:
                    new_lines.append(line)
                    continue

                parts = stripped.split()

                # Only modify lines with at least two numeric columns
                try:
                    x = float(parts[0])
                    y = float(parts[1])

                    y = -y
                    parts[1] = f"{y:.12g}"

                    new_lines.append("\t".join(parts) + "\n")

                except ValueError:
                    # Header or non-numeric line: keep unchanged
                    new_lines.append(line)

            with txt.open("w", encoding="utf-8") as f:
                f.writelines(new_lines)

            processed_files += 1

        except Exception as e:
            print(f"Error processing {txt}: {e}")

    print(f"✓ Finished folder: {subfolder.name}")

print("\n" + "=" * 60)
print(f"Done! Processed {processed_files} TXT files.")
print("=" * 60)