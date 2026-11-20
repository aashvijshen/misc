# Maker Deck & Cost Studio (`tools/showcase`)

Minimal, mobile-first showcase deck, profit-margin calculator, photo/GIF/video gallery manager, and offline UPI/WhatsApp quote tool.

## Launch

```bash
python3 tools/showcase/server.py 8090
```

Open **http://localhost:8090**.

## Highlights

- **Minimal Deck**: Clean `4:5` touch-swipe cards showing only media + name + single selling price (`₹`).
- **Tap Card → Bottom Sheet**: Variant toggle, color dots, **`Share`** (stamped Price Card or original photo/GIF/video clip + concise 2-line message), **`WhatsApp`**, and offline **`UPI QR`**.
- **`✎ Media` Manager**: Upload multiple photos, `.gif`s, or short `.mp4`/`.mov`/`.webm` rotation clips (streamed via HTTP `206 Range`), set cover order, and permanently delete placeholder CAD `previews/` renders (`excludedMedia`).
- **Cost & Profit Margin Calculator**: Live color-coded **Margin % vs. COGS** and **Net Margin % after Craft Labor** across both Deck items and internal drafts (`habit_tree`, etc.).
