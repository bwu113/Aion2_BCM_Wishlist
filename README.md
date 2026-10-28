# BCM Wishlist (AION 2)

BCM Wishlist watches the **Black Cloud Merchant** shop in AION 2 and tells you when something on **your wishlist** is for sale. You build a list of the pets, skins and Theostones you want. When you open the merchant in the game, the program checks every item in the shop against your list. Matches light up in a small overlay next to the program window, and it plays a short door-bell chime.

It only reads the game's network traffic on your PC. It never changes the game, sends anything to the game, or plays for you.

## Before you start

You need **[Npcap](https://npcap.com/)** installed, which is how the program reads the game's network traffic. During its setup, keep **"Install Npcap in WinPcap API-compatible Mode"** ticked.

Nothing else is needed. No Python and no installer: download `BCMWishlist.exe` from the [Releases page](../../releases) and run it. The first time, Windows may show a SmartScreen warning: click **More info**, then **Run anyway**.

## How to use it

1. **Add what you want.** Type in the box (for example `gravi` or `glacier mace`), pick an item from the dropdown and click **Add**. Small typos are handled, and capital letters don't matter. To add many at once, click **Paste list** and paste one name per line. The list holds up to 100 items. **Delete selected** removes one item and **Clear all** empties the list. The list is saved next to the program in `wishlist.json`.
2. Click **Start Scan**.
3. In the game, open the Black Cloud Merchant and click **each tab** (Special, Pets, Skins). The game only sends a tab's items when you open it.
4. Wanted items show up in the overlay and in your wishlist, with a chime. The **Chime volume** slider sets how loud it is (0 is silent), and **Test** plays it.
5. The scan **stops by itself** once all three tabs (Special, Pets, Skins) have been read. **Stop Scan** ends it earlier, and you can click **Start Scan** again at any time. **Show Overlay / Hide Overlay** toggles the overlay at any time.

### How to read the overlay

The overlay appears to the right of the program window as soon as the first shop page is read. It looks like the in-game shop:

- **Tabs** along the top (Special, Pets, Skins). Click one to look at it. It also follows the tab you open in the game.
- **Cards** for the items on the page. Each card shows the item's **name**, a large coloured **type** label (**PET** teal, **SKIN** purple, **STONE** orange) and the **quantity** left.
- **Green glowing cards** are items on your wishlist. They are repeated by name in the middle under **WANTED HERE**.
- Prices and discounts are not shown, and the game doesn't send item pictures, so the type label stands in for the artwork.

The overlay follows the program window when you move or resize it. It stays on top of the game, and it hides itself while some other program (a browser, for example) is in front, then comes back when you return to the game or the program. To see it over the game, run the game in **borderless / windowed** mode, not exclusive fullscreen.

## Troubleshooting

| What you see | What to do |
|---|---|
| **"Npcap is not installed"** | Install [Npcap](https://npcap.com/) (keep WinPcap API-compatible mode ticked), then click **Start Scan** again. |
| **"No game traffic seen yet"** | Make sure the game is running and connected. If it stays empty, close the program and start it again with right-click → **Run as administrator**. |
| **Traffic is seen but the overlay stays empty** | Open the merchant and click **each tab** after **Start Scan**. If a page was missed, switch to another tab and back. |
| **The overlay doesn't show over the game** | Switch the game to borderless/windowed mode. Also check **Show Overlay**, because the overlay stays hidden if you hid it yourself, and note that it hides while another program is in front. |
| **"Please download a new version"** | The game was probably updated and the shop no longer looks the way this version expects. Download the latest version from the [Releases page](../../releases). |
| **A pop-up asks you to name an item** | The game added an item the program doesn't know yet. Enter its name and pick a type, or click **Skip**. It is remembered in `item_catalog.csv`. |
| **"Your list is full"** | The limit is 100 items. Delete something first. |
| **No chime** | Check that the **Chime volume** slider isn't at 0, then click **Test**. |
| **Wishlist missing or reset** | A damaged `wishlist.json` is copied to `wishlist.json.bad` and the program starts with what it could read. If the program folder is read-only, the list is saved in `%APPDATA%\BCMWishlist`. |
| **SmartScreen blocks the exe** | Click **More info**, then **Run anyway**. |

## Privacy

BCM Wishlist does not send any information to other computers or services. It reads the game's network traffic on your own PC (through Npcap) and keeps your wishlist and learned items in files next to the program (or in `%APPDATA%\BCMWishlist`). It has no telemetry, no update check and no account. Npcap is a separate program with its own [license](https://npcap.com/oem/) and terms.

---

Free code signing by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org). See the [code signing policy](CODE_SIGNING_POLICY.md).
