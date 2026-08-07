# Brand assets

The icon Home Assistant shows for this integration — on *Settings → Devices &
services*, in HACS, and in the "add integration" dialog.

| File | What it is |
| --- | --- |
| `icon.svg` | The source. Hand-drawn; edit this one. |
| `icon.png` | 256×256, transparent, trimmed. What Home Assistant loads. |
| `icon@2x.png` | 512×512, the same image for high-density screens. |

## Why they are not in `custom_components/`

Home Assistant does not read brand images from an integration. They live in a
separate repository, [home-assistant/brands][brands], and the frontend fetches
them from `brands.home-assistant.io`. Until they are merged there, a custom
integration shows a generic puzzle piece — there is no local override, and
nothing in this repository can change that.

They are kept here so the source travels with the code that they represent.

## Submitting them

1. Fork and clone [home-assistant/brands][brands].
2. Copy the two PNGs into `custom_integrations/mealplan/`:

   ```
   custom_integrations/mealplan/icon.png      (256×256)
   custom_integrations/mealplan/icon@2x.png   (512×512)
   ```

3. Open a pull request. Their CI checks the dimensions, that the image is
   square, and that it is trimmed — no transparent margin around the artwork.
   Both files here already satisfy that; `icon.png` fills 252 of its 256 pixels
   horizontally and all 256 vertically.

Check their `CONTRIBUTING.md` at the time you submit: the requirements are theirs
to change, and this file is a snapshot of what they asked for in August 2026.

There is no `logo.png`. A logo is a wordmark shown on the integration page, and
"Meal Plan" set in a typeface adds nothing the icon and the title do not already
say.

## Regenerating the PNGs

The PNGs are rendered from `icon.svg` with headless Chrome — the same pipeline
the dashboard cards are checked with, so there is no extra dependency:

```bash
# render the SVG at 512 onto a transparent page, then crop, square and resample
chrome --headless --disable-gpu --allow-file-access-from-files \
       --default-background-color=00000000 --window-size=512,512 \
       --screenshot=icon-512.png shot.html
python -c "..."   # crop to getbbox(), pad to square, resize to 512 and 256
```

Two things to know if you edit the drawing:

* **Check it at 24 pixels**, not at 512. The head band is a solid block rather
  than a hairline rule precisely because a one-pixel line disappears at sidebar
  size, and a band is still a silhouette.
* **Chrome ignores `--window-size` for the viewport** in headless mode — it gave
  a 485-pixel viewport for a 390-pixel window while writing the dashboard cards.
  Render once at 512 and resample down rather than trusting a requested size.

[brands]: https://github.com/home-assistant/brands
