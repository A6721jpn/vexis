
import pandas as pd
import matplotlib.pyplot as plt
import sys, re
from pathlib import Path


def parse_rigid_body_data(log_path):
    """
    Parse rigid body data file and return DataFrame for plotting.
    
    Args:
        log_path: Path to the rigid body data file.
        
    Returns:
        DataFrame with columns ['Time', 'Stroke', 'Reaction_Force', 'Disp_Z', 'Force_Z']
        or None if parsing fails.
    """
    try:
        with open(log_path, 'r') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {log_path}: {e}")
        return None

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
        return None

    df = pd.DataFrame(data_rows, columns=['Time', 'RB_ID', 'Disp_Z', 'Force_Z'])
    
    # Transform Data
    # Stroke = Initial Z - Current Z (Assuming pressing down from positive Z)
    initial_z = df['Disp_Z'].iloc[0]
    df['Stroke'] = initial_z - df['Disp_Z']
    
    # Reaction Force = -1 * Force_Z (Assuming Force_Z is reaction in -Z direction)
    df['Reaction_Force'] = -1.0 * df['Force_Z']
    
    return df


def process_log(log_path, output_dir):
    """Process rigid body data and generate CSV + PNG outputs."""
    df = parse_rigid_body_data(log_path)
    if df is None:
        return

    # Save CSV
    out_dir = Path(output_dir)
    out_dir.mkdir(exist_ok=True, parents=True)
    csv_path = out_dir / "force_displacement.csv"
    df[['Time', 'Stroke', 'Reaction_Force', 'Disp_Z', 'Force_Z']].to_csv(csv_path, index=False)
    print(f"Saved CSV: {csv_path}")

    # Plot - Dark Theme (PNG still generated for backward compatibility)
    plt.style.use('dark_background')
    plt.rcParams.update({
        "figure.facecolor": "#0B0F14",
        "axes.facecolor": "#0B0F14",
        "axes.edgecolor": "#243244",
        "axes.labelcolor": "#EAF2FF",
        "xtick.color": "#6F8098",
        "ytick.color": "#6F8098",
        "grid.color": "#243244",
        "text.color": "#EAF2FF",
        "figure.autolayout": True
    })

    plt.figure(figsize=(10, 6))
    plt.plot(df['Stroke'], df['Reaction_Force'], marker='o', 
             color='#2EE7FF', markeredgecolor='white', markersize=4,
             linewidth=2, label='KEYCAP Reaction')
    
    # Use job name (log filename stem) as title
    job_name = Path(log_path).stem
    plt.title(job_name, color='#EAF2FF', fontsize=12, fontweight='bold')
    plt.xlabel('Stroke (mm)', fontsize=10)
    plt.ylabel('Reaction Force (N)', fontsize=10)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend(facecolor='#141E2A', edgecolor='#243244', labelcolor='#EAF2FF')
    
    png_path = out_dir / "force_displacement.png"
    plt.savefig(png_path, dpi=100, bbox_inches='tight')
    plt.close()
    print(f"Saved Graph: {png_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:  print("Usage: <log> <out_dir>"); sys.exit(1)
    process_log(sys.argv[1], sys.argv[2])
