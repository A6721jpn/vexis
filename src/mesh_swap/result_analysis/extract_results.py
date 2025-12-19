
import pandas as pd
import matplotlib.pyplot as plt
import sys, re
from pathlib import Path

def process_log(log_path, output_dir):
    with open(log_path, 'r') as f:
        content = f.read()

    # Parse the rigid body data file format
    # *Step  = 0
    # *Time  = 0
    # *Data  = KEYCAP
    # 3 3 0
    
    data_rows = []
    current_time = None
    
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Support both *Time and Time = formats
        if line.startswith("*Time") or line.startswith("Time"):
            try:
                parts = line.split("=")
                if len(parts) > 1:
                    current_time = float(parts[1].strip())
            except: pass
        elif line.startswith("*Data") or line.startswith("Data"):
            # Next line has the data
            if i + 1 < len(lines):
                data_line = lines[i+1].strip()
                parts = data_line.split()
                if len(parts) >= 3 and current_time is not None:
                     # ID, Val1, Val2
                     try:
                         rb_id = int(parts[0])
                         v1 = float(parts[1])
                         v2 = float(parts[2])
                         data_rows.append([current_time, rb_id, v1, v2])
                     except: pass
                i += 1
        i += 1

    if not data_rows:
        print(f"No data parsed from {log_path}.")
        return

    df = pd.DataFrame(data_rows, columns=['Time', 'RB_ID', 'Disp_Z', 'Force_Z'])
    
    # Transform Data
    # Stroke = Initial Z - Current Z (Assuming pressing down from positive Z)
    initial_z = df['Disp_Z'].iloc[0]
    df['Stroke'] = initial_z - df['Disp_Z']
    
    # Reaction Force = -1 * Force_Z (Assuming Force_Z is reaction in -Z direction)
    df['Reaction_Force'] = -1.0 * df['Force_Z']

    # Save CSV
    out_dir = Path(output_dir)
    out_dir.mkdir(exist_ok=True, parents=True)
    csv_path = out_dir / "force_displacement.csv"
    df[['Time', 'Stroke', 'Reaction_Force', 'Disp_Z', 'Force_Z']].to_csv(csv_path, index=False)
    print(f"Saved CSV: {csv_path}")

    # Plot
    plt.figure(figsize=(8, 6))
    plt.plot(df['Stroke'], df['Reaction_Force'], marker='o', label='KEYCAP Reaction')
    plt.title('Force vs Stroke')
    plt.xlabel('Stroke (mm)')
    plt.ylabel('Reaction Force (N)')
    plt.grid(True)
    plt.legend()
    
    png_path = out_dir / "force_displacement.png"
    plt.savefig(png_path)
    print(f"Saved Graph: {png_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:  print("Usage: <log> <out_dir>"); sys.exit(1)
    process_log(sys.argv[1], sys.argv[2])
