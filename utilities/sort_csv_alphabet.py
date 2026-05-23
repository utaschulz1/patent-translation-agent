import argparse
import os
import pandas as pd


def get_max_columns(file_path):
    """Scans the file to find the row with the most columns."""
    max_cols = 0
    # Opening with errors='ignore' ensures weird symbols won't crash the script
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            # Count how many commas are in this specific line
            col_count = len(line.split(","))
            if col_count > max_cols:
                max_cols = col_count
    return max_cols


def sort_csv(file_path):
    if not os.path.exists(file_path):
        print(f"Error: The file '{file_path}' does not exist.")
        return

    try:
        # 1. Figure out the widest row in the entire file
        max_cols = get_max_columns(file_path)

        if max_cols == 0:
            print("The provided CSV file is empty.")
            return

        # 2. Create placeholder column names based on the max count
        # e.g., [0, 1, 2, 3, 4] if the longest row has 5 columns
        col_names = list(range(max_cols))

        # 3. Read the file telling pandas to expect up to 'max_cols' columns.
        # Short rows will automatically be filled with 'NaN' (blank) at the end.
        df = pd.read_csv(
            file_path, names=col_names, header=None, engine="python"
        )

        # 4. Sort strictly by the very first column (index 0)
        df_sorted = df.sort_values(by=0, ascending=True)

        # 5. Create the output filename
        dir_name, file_name = os.path.split(file_path)
        output_path = os.path.join(dir_name, f"sorted_{file_name}")

        # 6. Save the sorted data
        # header=False ensures we don't write our dummy [0, 1, 2...] numbers to the new file
        df_sorted.to_csv(output_path, index=False, header=False)

        print(
            f"Success! Handled a ragged file (Max columns found: {max_cols})."
        )
        print(f"Saved to: {output_path}")

    except Exception as e:
        print(f"An error occurred while processing the file: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sort an inconsistent/ragged CSV file alphabetically by its first column."
    )
    parser.add_argument(
        "-f",
        "--file",
        required=True,
        help="Path to the CSV file you want to sort",
    )

    args = parser.parse_args()
    sort_csv(args.file)