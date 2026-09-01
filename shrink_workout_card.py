import re

files = [
    "frontend/index.html",
    "backend/static/index.html"
]

for file_path in files:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Workout card font sizes and margins
        # <div style="font-size:16px; font-weight:700; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
        content = content.replace(
            '<div style="font-size:16px; font-weight:700; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">',
            '<div style="font-size:15px; font-weight:700; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">'
        )
        
        # <div style="font-size:12px; color:var(--text-muted); margin-top:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
        content = content.replace(
            '<div style="font-size:12px; color:var(--text-muted); margin-top:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">',
            '<div style="font-size:12px; color:var(--text-muted); margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">'
        )

        # Shrink the buttons padding slightly to make the row height compact
        # Workout buttons
        content = content.replace('padding:6px; transition:0.2s;"><svg width="20" height="20"', 'padding:4px; transition:0.2s;"><svg width="18" height="18"')
        
        # Also ensure the icons scale down to 18x18 instead of 20x20
        # This reduces the overall line height forced by flex items
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        print(f"Fixed {file_path}")
    except Exception as e:
        print(f"Error on {file_path}: {e}")
