# Eddie Finds — local-image version

This version automatically imports your public Doppel catalogue and downloads the product images into your GitHub repository.

## Upload
1. Create a GitHub repository such as `eddie-finds`.
2. Upload the entire contents of this ZIP.
3. Settings → Pages → Deploy from branch → `main` → `/ (root)`.
4. Actions → `Import Doppel catalogue` → Run workflow.

## What happens during an import
For each discovered product the importer attempts to collect:
- product name
- category
- Doppel product image
- final external item URL

The image is downloaded to:
`images/products/`

The generated JSON then contains a local image path such as:
`"image": "images/products/bape-shirt-0001-a1b2c3d4e5.jpg"`

The original online image is retained as:
`"remote_image": "https://..."`

The GitHub Action commits both `data/products.json` and `images/products/`.

The importer also removes downloaded product images that are no longer in the current catalogue.

## Doppel source already configured
`https://doppel.fit/@EddieFinds/eddie-find/tshirts`

Add more category URLs under `seed_urls` in `config.json` if they are not automatically discovered.
