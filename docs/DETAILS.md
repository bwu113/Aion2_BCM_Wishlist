# BCM Wishlist (AION 2)

Passive packet capture that decodes the **Black Cloud Merchant** shop, checks it against **your wishlist** and shows where the wanted items are in an overlay docked to the right of the program window (dark theme).

It does not inject packets, modify game memory or automate gameplay. Review the game publisher's rules for third-party tools before use.

## Getting the program

**Requirement on the PC that runs it: [Npcap](https://npcap.com/)** (install with "WinPcap API-compatible mode" ticked). Nothing else - no Python, no installer: `BCMWishlist.exe` is a single self-contained file. Windows SmartScreen may warn about an unrecognised or unsigned program the first time: *More info > Run anyway*. If capture finds nothing, start it with right-click > *Run as administrator*. If Npcap is missing the program says so and links to the download.

Two ways to produce the exe (done once by whoever distributes it):
- **On a Windows PC with Python 3.10+:** double-click `Build_EXE.bat` -> `dist\BCMWishlist.exe`.
- **Without installing anything:** put this folder in a GitHub repository, open *Actions > Build Windows exe > Run workflow*, and download the exe from the finished run (`.github/workflows/build-exe.yml`).

Share just the exe. Your wishlist is saved as `wishlist.json` next to it (or in `%APPDATA%\BCMWishlist` if that folder is read-only).

## Using it

1. **Add what you want:** click the dropdown (or just start typing) - it lists every pet, skin and Theostone in the item list, and typing narrows it down (`gravi`, `glacier mace`, `reda`). Pick one with the mouse or Up/Down + Enter, then click **Add**. To remove something select it and click **Delete selected** (or press Delete). **Clear all** (top right of the list heading) empties the whole list after a confirmation; the chime volume is kept.
   - The wishlist holds **at most 100 items** (the heading shows `n / 100`); delete something to add more. The limit is `MAX_WISHLIST` in `wishlist.py`.
   - **Misspellings in the dropdown:** if no item contains the words you typed, the dropdown lists look-alikes (marked `(similar)`): `krall warior` shows Pet: Krall Warrior, `gravy` shows Pet: Gravi and a few close names. Pick one as usual.
   - **If you click Add without picking:** if what you typed matches no item, **Add** looks for the closest one. A clear typo (`Krall Warior`) is corrected and added, and the status line says so. A rougher one (`gravy`) opens the same pop-up as Paste list with the closest items to pick from. Capitals never matter.
   - Text that matches nothing even loosely (e.g. `Nameless Master`) can be added as a **keyword** matching every shop item whose name contains it.
   - **Paste list:** click **Paste list**, paste many names (one per line; commas, bullets and numbering are fine; "Paste from clipboard" does it for you) and click **Add to wishlist**. Each name is matched to the item list as closely as possible: capitals, small typos and the loose words `pet`, `skin`, `godstone`, `theostone`, `bound` and `other` are ignored (so `gravi pet` = `Gravi`, `Reda's Tenacity theostone` = `Reda's Tenacity`, `(Bound)` is dropped, and a line holding only such a word is skipped), but the same words followed by a colon are part of the item's name and are kept (`Pet: Gravi`, `Theostone: Reda's Tenacity`, `(Skin: Mace)`). Typo fixes are reported. If a name fits several items (e.g. just `judicator`), or only roughly fits one, a pop-up asks you to resolve it, one name at a time: pick one or several items, or cancel the rest. Names that match nothing stay in the box with the reason. If the pasted list does not fit under the 100-item limit, the first items are added and the rest are cut off; a notice with an OK button lists exactly what was cut off (no questions are asked about names that would be cut anyway).
2. Click **Start Scan**. The overlay opens to the right of the window by itself as soon as the first shop page is captured (nothing is drawn before that).
3. In the game open the Black Cloud Merchant and click **each tab** (Special, Pets, Skins). The server only sends a tab's items when you open it.
4. Wanted items light up in the overlay and the list shows where each one is ("Special #3 (top row, 3rd from left)"). A new match also plays a short shop-door bell chime (`found_chime.wav`; swap in your own WAV with the same name to change it) and shows a FOUND line. The **Chime volume** slider next to Delete selected sets how loud it is (default 50 %, 0 = silent); **Test** plays it, and the setting is remembered in `wishlist.json`. **Stop Scan** ends the capture.
5. **Show Overlay / Hide Overlay** toggles the overlay at any time, even before scanning; the button always shows what a click will do. If you hide the overlay yourself it stays hidden until you show it again.

### The window and the overlay

- The overlay is a compact replica of the in-game shop: tabs on top, then 10 hanging cards (6 on the top row, 4 on the bottom row under the outer columns, leaving the middle free for the merchant and the "WANTED HERE" list). Each card shows the item name, a big colour-coded **item type** in the centre (PET teal, SKIN purple, STONE orange) and the quantity. Wanted items get a bright green card with a glow and are repeated by name in the middle ("WANTED HERE"). Prices, discounts and card numbers are deliberately not shown. Click a tab in the overlay to look at it; it also follows the tab you open in the game.
- The overlay is docked to the right edge of the program window, top-aligned, and scales with it: its height is 80 % of the window's height (default window 460 x 486 -> overlay 655 x 389). Resize the window and the overlay resizes (the window is the only handle). It follows when you move the window and hides when you minimise it.
- **Minimum size:** the window cannot be made shorter than about 479 px, because below that the overlay (then 645 x 383) would stop being readable: item names shrink to a 10 px minimum and wrap to as many lines as fit, and at the minimum size every item in the list still fits without being cut off.
- **Multiple monitors:** the overlay always stays on the monitor the program is on (docked on the right; if there is no room there, on the left; if neither fits it is tucked against the monitor's edge). Move the program to another monitor and the overlay follows. Borderless/windowed fullscreen is needed for the overlay to show over the game.
- **Order of cards:** the packets contain the items but not their screen positions. The program shows them sorted by entry ID (Theostones, then skins, then pets in the Special tab), which matches the in-game screenshot this overlay was modelled on. This is an inference - if the game's order ever differs, `build_views(..., sort_by_entry=False)` in `wishlist.py` switches to raw packet order. The wishlist in the main window still lists where each wanted item is ("Special #3 (top row, 3rd from left)").
- Item icons are not in the packets, so the type label stands in for the artwork.

## Item list

`aion2_items.csv` (item_id, name, type) was compiled from aion2hub.com (a fan database that reads the game client's data):

| Part | Rows | Source |
|---|---|---|
| Pets | 497 | `database?q=Pet:` search (214 shop items "Pet: X") + `cosmetics?kind=pet` (creatures; Gravi exists as both 534660051 and 534760049) |
| Skins | 2,619 | `database?q=Skin:` search (1,612 items) + `cosmetics?kind=skin` (2,394 entries) |
| Theostones | 102 | the Materials > Godstone list (unbound and bound versions) |

- The **shop sells the "Pet: X" and "(Skin: X) (Bound)" items** (IDs 5347…, 5357…, 5358…, …). The cosmetics page lists some of these under other IDs (pet creatures `5346…`, some skin sets `110…`), so the program matches by **normalised name** as well as by ID: picking "Gravi" matches the shop's Pet: Gravi, picking "Glacier's Judgment (Mace)" matches the shop's Glacier's Judgment (Skin: Mace) (Bound).
- Checks: the 29 pet/skin items seen in the included capture all matched by ID and exact name in the independent search scrape; the cosmetics and search scrapes agree on 1,357 of 1,387 shared IDs (the rest are renamed items, e.g. "Balance Arbiter" vs "Heritage Arbiter").
- Known gaps: about 36 entries on aion2hub have **no ID at all** (shown as plain text: e.g. Gold/Silver/Bronze Void pets, Crown Chess (Fist), several "Neo Ranger Suit"/"Sporty Rash Guard" pieces) and are not in the list. The site lists new content over time, and the list is a snapshot from 2026-10-16.
- Unknown items still appear in the overlay as "Unknown item <id>". Add a line `item_id,name,type` to `item_catalog.csv` to name one yourself (your entries win over `aion2_items.csv`). You can also look any ID up at `https://aion2hub.com/database/items/<id>`.

## Protocol notes (reverse-engineered from black_cloud_merchant_2.pcap)

- Game connection: TCP `193.202.112.2:13328`. Server -> client is **plaintext**; client -> server is encrypted/obfuscated and not needed. (The big UDP flow in the capture was voice chat.)
- Framing: `varint(length) + payload`, payload = `length - 4` bytes, first 2 payload bytes = opcode. `00 36`/`03 36` = 20 Hz server clock tick (epoch ms) - the decoder uses it to lock onto the stream even if a scan starts mid-connection and recovers from dropped packets.
- Shop list opcode `91 56`: `[request id][entry count]` then 34-byte entries: `u32 entry_id, u32 item_id, u64 quantity, u8 discount_tier, 0x5d, u64 original_price, u64 price` (one extra control byte before entries 1, 5, 9, …; trailer = server time).
- `entry_id // 10000` = tab: 11 Special, 12 Pets, 13 Skins. Discount tiers seen: 0 = -10%, 1 = -20%, 2 = -30%, 3 = -50% (the app uses the two prices to compute the percentage).
- All inferred from a single capture: a game update could change the format. `python shop_decoder.py capture.pcap` decodes a classic .pcap without the GUI.
- If the capture driver drops packets that contained a shop page, that page is skipped - just re-open the tab.

## Performance (why it is light)

- **Capture reads Npcap directly** (`npcap_native.py`, no Scapy in the normal path) and parses only the TCP header by hand: about 12 microseconds per game packet; the game sends roughly 25 per second, so the CPU use is far below 1 %.
- **The driver does the filtering.** At first only TCP packets that carry data are captured. As soon as the game's connection is recognised (its 20 Hz heartbeat) the Npcap filter is narrowed to "TCP from that server address and port", the other network adapters are closed, and everything else - browser, downloads, voice chat - never reaches the program. If the game connection goes silent for 20 s the wide filter is restored automatically.
- Other connections that show no game heartbeat within 40 packets are ignored from then on (one dictionary lookup per packet).
- The window runs at below-normal priority, so the game always gets the CPU first. Packet decoding happens in the capture thread, not in the window.
- **Graphics:** the overlay is a plain opaque window with a small canvas (no transparency, no animation). It only redraws when its size, the visible tab or the shop contents change (identical updates are skipped, window drags are merged to about 30 redraws/second at most), and the "stay docked" check runs twice a second and does nothing unless the window moved.
- When idle the program wakes up a few times a second. The item dropdown pre-computes its search text once, so typing stays instant.
- Scapy (`scapy_backend.py`) is only a fallback if the direct Npcap access cannot start and Scapy is present; it loads lazily, so it costs nothing otherwise.

## Troubleshooting

- **"Npcap is not installed":** install it from https://npcap.com (keep "WinPcap API-compatible mode" ticked) and click Start Scan again.
- **"No game traffic seen yet":** the game is not connected yet, or capture needs more rights - start the program with right-click > *Run as administrator*. Capture covers every adapter that has an IP address (VPNs and game boosters included).
- **Traffic but no shop tabs:** open the merchant / switch tabs *after* Start Scan. If a packet carrying a shop page was dropped, just re-open that tab.
- To check a capture file without the GUI: `python shop_decoder.py yourfile.pcap`. PCAP files contain network metadata - keep them private.

## Files

- `BCMWishlist.pyw` - main window, scan control, overlay docking
- `safety.py` - the safety net that judges shop pages (new items vs. a changed game)
- `bulk_add.py` / `paste_dialog.py` - the Paste list window and its name matching
- `found_chime.wav` - the sound played when a wanted item is found (0.55 s slice of "Shopkeepers Bell Sound Effects [Free Audio]" by Sound Bytes on YouTube - check the channel's terms before sharing the program publicly); `chime.py` - volume scaling and playback
- `bcm_icon.ico` / `bcm_icon.png` - the program icon (the merchant animal cut out of the picture you supplied, background removed)
- `ui_widgets.py` - searchable item dropdown and overlay window; `theme.py` - dark colours
- `npcap_native.py` - lean packet capture straight from Npcap (ctypes); `scapy_backend.py` - fallback through Scapy
- `wishlist.py`, `catalog.py` - wishlist model / matching, item list and name matching (no GUI code)
- `shop_decoder.py` - stream framing and shop decoder (also a CLI)
- `aion2_items.csv`, `item_catalog.csv` - item lists (the first is built into the exe); `wishlist.json` is created on first use
- `Build_EXE.bat`, `.github/workflows/build-exe.yml` (build the single exe), `Run_Source.bat`, `requirements.txt`

## Safety net (game updates, unknown items, damaged files)

The program is built not to crash, whatever the game sends:

- **A few items that are not in the item list** (the game added pets/skins): the program remembers them at once by ID in your own list, `item_catalog.csv` (shown on the overlay as `Unknown item <ID>`), and opens a pop-up for each one asking for its **name** and **type** (Pet / Skin / Theostone / Other; the type is pre-selected with a guess). **Save** stores the real name and type; **Skip** keeps `Unknown item <ID>`; **Skip all** skips the rest of the questions. The pop-ups do not block anything and come one after another. You can look an ID up at `https://aion2hub.com/database/items/<ID>`. Pets are stored as `Pet: Name` and Theostones as `Theostone: Name`, like the built-in list. The game never sends item names, which is why it has to ask. The built-in `aion2_items.csv` lives inside the exe and cannot change while it runs, so `item_catalog.csv` is where learned items go; it is read at every start and wins over the built-in list.
- **The shop no longer looks the way this version expects** (the game was probably updated): an unknown shop tab, shop entries that cannot be read, items of the wrong type for their tab, several IDs far outside every known range, or most of a page missing from the item list. The program then says **"Please download a new version"** (once per scan, in a pop-up that does not block anything) and learns nothing from that page, so bad data never ends up in your list.
- **Unexpected errors** anywhere in the program are caught: the status line says what happened and the program keeps running. A message that cannot be processed is skipped, and the next one is handled normally.
- **A damaged `wishlist.json`** never stops the program or silently wipes your list: unreadable entries are skipped, and an unreadable file is first copied to `wishlist.json.bad`.

## Privacy

BCM Wishlist does not send any information to other computers or services. It reads the game's network traffic on your own PC (through Npcap) and keeps your wishlist and learned items in files next to the program (or in `%APPDATA%\BCMWishlist`). It has no telemetry, no update check and no account. Npcap is a separate program with its own [license](https://npcap.com/oem/) and terms.
