import re

files = [
    "frontend/index.html",
    "backend/static/index.html"
]

for file_path in files:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Fix the syntax error in line 7256
        old_str = "grid-template-columns:repeat(2,minmax(0,1fr)}}"
        new_str = "grid-template-columns:repeat(2,minmax(0,1fr))}}"
        content = content.replace(old_str, new_str)
        
        # In case the exact match is slightly different (e.g. missing whitespace)
        # We can also do a regex replace
        content = re.sub(r'grid-template-columns:repeat\(([^)]*),minmax\(([^)]*)\)\}\}', r'grid-template-columns:repeat(\1,minmax(\2))}}', content)

        # Append global fix before </head>
        global_mobile_css = """
<style id="mobile-expert-fix">
@media (max-width: 900px) {
  /* Prevent horizontal scrolling globally */
  html, body {
    overflow-x: hidden !important;
    width: 100% !important;
    max-width: 100vw !important;
  }
  
  /* Make sure all expert grids collapse nicely */
  .expert-layout,
  .expert-gym-workspace,
  .expert-gym-bottom-grid,
  .expert-data-grid,
  .expert-equipment-groups,
  .expert-form-grid,
  .expert-data-choice-grid,
  .expert-data-doms-grid,
  .expert-doms-row {
    grid-template-columns: 1fr !important;
    gap: 12px !important;
  }
  
  .expert-gym-stat-grid,
  .expert-choice-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
  }
  
  @media (max-width: 480px) {
    .expert-gym-stat-grid,
    .expert-choice-grid {
      grid-template-columns: 1fr !important;
    }
  }

  .expert-equipment-layout {
    grid-template-columns: 1fr !important;
  }

  /* Handle inputs and buttons on mobile */
  .expert-data-tabs {
    flex-wrap: nowrap;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 8px;
  }
  
  .expert-data-actions {
    flex-direction: column;
  }
  
  .expert-data-actions .btn {
    width: 100% !important;
    margin-bottom: 8px;
    flex: none !important;
  }

  /* Prevent text and element squeezing */
  .expert-card, .expert-equipment-group, .expert-data-card {
    min-width: 0 !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
    word-wrap: break-word !important;
    overflow: hidden !important;
  }
  
  /* Make tables and wide content scrollable */
  .expert-table-wrap, .table-wrap {
    overflow-x: auto !important;
    width: 100% !important;
    -webkit-overflow-scrolling: touch !important;
  }
}
</style>
"""
        
        # Only add if not already there
        if 'id="mobile-expert-fix"' not in content:
            content = content.replace("</head>", global_mobile_css + "\n</head>")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        print(f"Fixed {file_path}")
    except Exception as e:
        print(f"Error on {file_path}: {e}")
