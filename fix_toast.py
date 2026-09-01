import re

files = [
    "frontend/index.html",
    "backend/static/index.html"
]

for file_path in files:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        toast_css = """  /* Toast notifications mobile shrink */
  .toast {
    padding: 10px 16px !important;
    font-size: 11px !important;
    border-radius: 20px !important;
    gap: 6px !important;
    max-width: 90% !important;
    line-height: 1.3 !important;
  }
  .toast svg {
    width: 16px !important;
    height: 16px !important;
    flex-shrink: 0 !important;
  }
"""

        # Inject right after @media (max-width: 768px) { inside mobile-shrink-fix
        if "/* Toast notifications mobile shrink */" not in content:
            content = content.replace(
                "<style id=\"mobile-shrink-fix\">\n@media (max-width: 768px) {",
                f"<style id=\"mobile-shrink-fix\">\n@media (max-width: 768px) {{\n{toast_css}"
            )
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Fixed {file_path}")
        else:
            print(f"Toast CSS already in {file_path}")
            
    except Exception as e:
        print(f"Error on {file_path}: {e}")
