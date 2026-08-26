const SHEET_URL =
  "https://docs.google.com/spreadsheets/d/e/2PACX-1vTtd7p-OOSoZOCJ9TsnCA2DlYWieTIQrZiU5DkHhCU48HGeYjvFksGSWglq7CTyW7ueCV8yARt7fgAv/pub?gid=667735791&single=true&output=csv";

const grid = document.getElementById("grid");
const statusEl = document.getElementById("status");
const count = document.getElementById("count");
const categories = document.getElementById("categories");
const subcategories = document.getElementById("subcategories");
const search = document.getElementById("search");
const sort = document.getElementById("sort");
const template = document.getElementById("cardTemplate");

let products = [];
let activeCategory = "All";
let activeSubcategory = "All";

function parseCSV(text) {
  const rows = [];
  let row = [];
  let field = "";
  let insideQuotes = false;

  for (let i = 0; i < text.length; i++) {
    const char = text[i];

    if (char === '"') {
      if (insideQuotes && text[i + 1] === '"') {
        field += '"';
        i++;
      } else {
        insideQuotes = !insideQuotes;
      }
    } else if (char === "," && !insideQuotes) {
      row.push(field);
      field = "";
    } else if ((char === "\n" || char === "\r") && !insideQuotes) {
      if (char === "\r" && text[i + 1] === "\n") i++;

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

  if (field || row.length) {
    row.push(field);
    if (row.some(cell => cell !== "")) rows.push(row);
  }

  return rows;
}

function rowsToProducts(rows) {
  if (!rows.length) return [];

  const headers = rows[0].map(h => (h || "").trim());

  return rows.slice(1).map(row => {
    const item = {};

    headers.forEach((header, index) => {
      item[header] = (row[index] || "").trim();
    });

    return item;
  }).filter(item => {
    const active = (item["Active"] || "").toUpperCase();
    return item["Name"] &&
           item["Product Link"] &&
           active !== "FALSE";
  });
}

function parsePrice(item) {
  const value = parseFloat((item["Price"] || "").replace(",", "."));
  return Number.isFinite(value) ? value : null;
}

function formatPrice(item) {
  const price = item["Price"];
  if (!price) return "";

  const currency = item["Currency"];

  if (currency === "GBP") return "£" + price;
  if (currency === "EUR") return "€" + price;
  if (currency === "USD") return "$" + price;
  if (currency === "DKK") return price + " kr";

  return price;
}

function isFeatured(item) {
  return (item["Featured"] || "").toUpperCase() === "TRUE";
}

function renderCategories() {
  const list = [
    "All",
    ...new Set(products.map(p => p["Category"]).filter(Boolean))
  ].sort((a, b) => {
    if (a === "All") return -1;
    if (b === "All") return 1;
    return a.localeCompare(b);
  });

  categories.innerHTML = "";

  list.forEach(category => {
    const button = document.createElement("button");

    button.className =
      "cat" + (category === activeCategory ? " active" : "");

    button.textContent = category;

    button.onclick = () => {
      activeCategory = category;
      activeSubcategory = "All";
      renderCategories();
      renderSubcategories();
      renderProducts();
    };

    categories.appendChild(button);
  });
}

function renderSubcategories() {
  const relevant = products.filter(item =>
    activeCategory === "All" ||
    item["Category"] === activeCategory
  );

  const list = [
    "All",
    ...new Set(relevant.map(p => p["Subcategory"]).filter(Boolean))
  ];

  subcategories.innerHTML = "";

  if (list.length <= 1) {
    subcategories.style.display = "none";
    return;
  }

  subcategories.style.display = "flex";

  list.forEach(subcategory => {
    const button = document.createElement("button");

    button.className =
      "subcat" + (subcategory === activeSubcategory ? " active" : "");

    button.textContent = subcategory;

    button.onclick = () => {
      activeSubcategory = subcategory;
      renderSubcategories();
      renderProducts();
    };

    subcategories.appendChild(button);
  });
}

function getFilteredProducts() {
  const query = (search.value || "").trim().toLowerCase();

  let filtered = products.filter(item => {
    const categoryMatch =
      activeCategory === "All" ||
      item["Category"] === activeCategory;

    const subcategoryMatch =
      activeSubcategory === "All" ||
      item["Subcategory"] === activeSubcategory;

    const searchable = [
      item["Name"],
      item["Brand"],
      item["Category"],
      item["Subcategory"],
      item["Tags"]
    ].join(" ").toLowerCase();

    return categoryMatch &&
           subcategoryMatch &&
           (!query || searchable.includes(query));
  });

  if (sort.value === "featured") {
    filtered.sort((a, b) => Number(isFeatured(b)) - Number(isFeatured(a)));
  }

  if (sort.value === "newest") {
    filtered.sort((a, b) =>
      (b["Date Added"] || "").localeCompare(a["Date Added"] || "")
    );
  }

  if (sort.value === "az") {
    filtered.sort((a, b) =>
      (a["Name"] || "").localeCompare(b["Name"] || "")
    );
  }

  if (sort.value === "priceLow") {
    filtered.sort((a, b) => {
      const ap = parsePrice(a);
      const bp = parsePrice(b);
      if (ap === null) return 1;
      if (bp === null) return -1;
      return ap - bp;
    });
  }

  if (sort.value === "priceHigh") {
    filtered.sort((a, b) => {
      const ap = parsePrice(a);
      const bp = parsePrice(b);
      if (ap === null) return 1;
      if (bp === null) return -1;
      return bp - ap;
    });
  }

  return filtered;
}

function renderProducts() {
  const filtered = getFilteredProducts();

  grid.innerHTML = "";

  count.textContent =
    filtered.length +
    (filtered.length === 1 ? " item" : " items");

  if (!filtered.length) {
    statusEl.hidden = true;
    grid.innerHTML = '<div class="empty">No products found.</div>';
    return;
  }

  statusEl.hidden = true;

  filtered.forEach(item => {
    const node = template.content.cloneNode(true);

    const card = node.querySelector(".product-card");
    const image = node.querySelector(".product-image");
    const imageLink = node.querySelector(".image-link");
    const button = node.querySelector(".view-button");

    if (isFeatured(item)) {
      card.classList.add("is-featured");
    }

    image.src =
      item["Image URL"] ||
      "https://placehold.co/800x900?text=Eddie+Finds";

    image.alt = item["Name"];

    image.onerror = () => {
      image.src = "https://placehold.co/800x900?text=Eddie+Finds";
    };

    imageLink.href = item["Product Link"];
    button.href = item["Product Link"];

    const meta = [item["Category"], item["Subcategory"]]
      .filter(Boolean)
      .join(" / ");

    node.querySelector(".product-meta").textContent = meta;

    node.querySelector(".product-name").textContent =
      item["Brand"]
        ? item["Brand"] + " — " + item["Name"]
        : item["Name"];

    node.querySelector(".product-price").textContent =
      formatPrice(item);

    grid.appendChild(node);
  });
}

async function loadProducts() {
  try {
    statusEl.hidden = false;
    statusEl.textContent = "Loading catalogue…";

    const response = await fetch(
      SHEET_URL + "&t=" + Date.now()
    );

    if (!response.ok) {
      throw new Error("Google Sheets returned " + response.status);
    }

    const text = await response.text();
    const rows = parseCSV(text);

    products = rowsToProducts(rows);

    renderCategories();
    renderSubcategories();
    renderProducts();

  } catch (error) {
    console.error(error);
    statusEl.hidden = false;
    statusEl.textContent = "Could not load Google Sheet.";
  }
}

search.addEventListener("input", renderProducts);
sort.addEventListener("change", renderProducts);

loadProducts();
