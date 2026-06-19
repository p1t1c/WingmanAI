import os
from PIL import Image, ImageDraw, ImageFont

# 1. Generate Icons
static_dir = r"c:\Users\oprea\Desktop\Generale\Generale\Hack\WingmanAI\static"
for size in [192, 512]:
    img = Image.new('RGB', (size, size), color='#1a1a1a')
    d = ImageDraw.Draw(img)
    # Just draw a simple logo or letter "W"
    text = "W"
    # Using default font since we might not have path to a good one, or just draw a circle
    d.ellipse([(size//4, size//4), (size*3//4, size*3//4)], fill='#00ffcc')
    img.save(os.path.join(static_dir, f"icon-{size}.png"))

print("Icons generated.")

# 2. Inject PWA tags into all HTML templates
templates_dir = r"c:\Users\oprea\Desktop\Generale\Generale\Hack\WingmanAI\templates"
injection = """
    <!-- PWA Setup -->
    <link rel="manifest" href="/static/manifest.json">
    <meta name="theme-color" content="#1a1a1a">
    <script>
      if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
          navigator.serviceWorker.register('/sw.js');
        });
      }
    </script>
"""

for filename in os.listdir(templates_dir):
    if filename.endswith(".html"):
        filepath = os.path.join(templates_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Avoid double injection
        if "manifest.json" not in content:
            content = content.replace("</head>", injection + "</head>")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

print("HTML injected.")
