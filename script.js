const SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTtd7p-OOSoZOCJ9TsnCA2DlYWieTIQrZiU5DkHhCU48HGeYjvFksGSWglq7CTyW7ueCV8yARt7fgAv/pub?gid=667735791&single=true&output=csv";

let allProducts = [];
let activeCategory = "All";

const grid = document.querySelector("#grid");
const search = document.querySelector("#search");
const categories = document.querySelector("#categories");
const count = document.querySelector("#count");
const statusEl = document.querySelector("#status");
const sort = document.querySelector("#sort");
const template = document.querySelector("#cardTemplate");

const clean = (v) => (v ?? "").toString().trim();

function parseCSV(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;

  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    const next = text[i + 1];

    if (char === '"') {
      if (quoted && next === '"') {
        field += '"';
        i++;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      row.push(field);
      field = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && next === "\n") i++;

      row.push(field);
      field = "";

      if (row.some(cell => cell !== "")) {
        rows.push(row);
      }

      row = [];
    } else {
      field += char;
    }
  }

  if (field.length || row.length) {
    row.push(field);

    if (row.some(cell => cell !== "")) {
      rows.push(row);
    }
  }

  return rows;
}

function rowsToProducts(rows) {
  if (!rows.length) return [];

  const headers = rows[0].map(h => clean(h));

  const index = Object.fromEntries(
    headers.map((h, i) => [h, i])
  );

  return rows.slice(1).map(row => ({
    id: clean(row[index["ID"]]),
    name: clean(row[index["Name"]]),
    brand: clean(row[index["Brand"]]),
    category: clean(row[index["Category"]]),
    subcategory: clean(row[index["Subcategory"]]),
    price: clean(row[index["Price"]]),
    currency: clean(row[index["Currency"]]),
    image: clean(row[index["Image URL"]]),
    link: clean(row[index["Product Link"]]),
    featured:
      clean(row[index["Featured"]]).toUpperCase() === "TRUE",
    tags: clean(row[index["Tags"]]),
    dateAdded: clean(row[index["Date Added"]]),
    active:
      clean(row[index["Active"]]).toUpperCase() !== "FALSE"
  }))
  .filter(product =>
    product.active &&
    product.name &&
    product.link
  );
}

function formatPrice(product) {
  if (!product.price) return "";

  const symbols = {
    GBP: "£",
    EUR: "€",
    USD: "$"
  };

  const value = product.price.replace(/\.00$/, "");

  if (product.currency === "DKK") {
    return `${value} kr`;
  }

  return `${symbols[product.currency] || ""}${value}`;
}

function renderCategories() {
  const categoryNames = [
    ...new Set(
      allProducts
        .map(product => product.category)
        .filter(Boolean)
    )
  ].sort((a, b) => a.localeCompare(b));

  const names = ["All", ...categoryNames];

  categories.innerHTML = "";

  names.forEach(name => {
    const button = document.createElement("button");

    button.className =
      "cat" + (name === activeCategory ? " active" : "");

    button.textContent = name;

    button.addEventListener("click", () => {
      activeCategory = name;
      renderCategories();
      render();
    });

    categories.appendChild(button);
  });
}

function getFilteredProducts() {
  const query = clean(search.value).toLowerCase();

  let products = allProducts.filter(product => {

    const categoryMatch =
      activeCategory === "All" ||
      product.category === activeCategory;

    const searchable = [
      product.name,
      product.brand,
      product.category,
      product.subcategory,
      product.tags
    ]
      .join(" ")
      .toLowerCase();

    return (
      categoryMatch &&
      (!query || searchable.includes(query))
    );
  });

  if (sort.value === "az") {
    products.sort((a, b) =>
      a.name.localeCompare(b.name)
    );
  }

  if (sort.value === "newest") {
    products.sort((a, b) =>
      clean(b.dateAdded).localeCompare(
        clean(a.dateAdded)
      )
    );
  }

  if (sort.value === "featured") {
    products.sort(
      (a, b) =>
        Number(b.featured) -
        Number(a.featured)
    );
  }

  return products;
}

function render() {
  const products = getFilteredProducts();

  grid.innerHTML = "";

  count.textContent =
    `${products.length} item${products.length === 1 ? "" : "s"}`;

  statusEl.hidden = true;

  if (!products.length) {
    grid.innerHTML =
      "<p>No products found.</p>";
    return;
  }

  products.forEach(product => {

    const node =
      template.content.cloneNode(true);

    const img =
      node.querySelector(".product-image");

    const imageLink =
      node.querySelector(".image-link");

    const button =
      node.querySelector(".view-button");

    img.src =
      product.image ||
      "https://placehold.co/800x900?text=Eddie+Finds";

    img.alt = product.name;

    img.loading = "lazy";

    img.onerror = () => {
      img.src =
        "https://placehold.co/800x900?text=Eddie+Finds";
    };

    imageLink.href = product.link;
    imageLink.rel = "noopener noreferrer";

    button.href = product.link;
    button.rel = "noopener noreferrer";

    node.querySelector(
      ".product-category"
    ).textContent =
      product.subcategory ||
      product.category;

    node.querySelector(
      ".product-name"
    ).textContent =
      product.brand
        ? `${product.brand} — ${product.name}`
        : product.name;

    node.querySelector(
      ".product-price"
    ).textContent =
      formatPrice(product);

    grid.appendChild(node);
  });
}

async function loadProducts() {
  try {

    statusEl.hidden = false;

    statusEl.textContent =
      "Loading catalogue…";

    const response = await fetch(
      `${SHEET_CSV_URL}&cache=${Date.now()}`
    );

    if (!response.ok) {
      throw new Error(
        `Google Sheets returned ${response.status}`
      );
    }

    const csv = await response.text();

    const rows = parseCSV(csv);

    allProducts = rowsToProducts(rows);

    renderCategories();

    render();

    if (!allProducts.length) {
      statusEl.hidden = false;

      statusEl.textContent =
        "No active products found. Check your Google Sheet.";
    }

  } catch (error) {

    console.error(error);

    statusEl.hidden = false;

    statusEl.textContent =
      "Could not load products from Google Sheets.";
  }
}

search.addEventListener(
  "input",
  render
);

sort.addEventListener(
  "change",
  render
);

loadProducts();
