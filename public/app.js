const state = {
  data: null,
  query: "",
};

const elements = {
  brandName: document.querySelector("#brandName"),
  brandSubtitle: document.querySelector("#brandSubtitle"),
  searchInput: document.querySelector("#searchInput"),
  productGrid: document.querySelector("#productGrid"),
  productCount: document.querySelector("#productCount"),
  emptyState: document.querySelector("#emptyState"),
  productTemplate: document.querySelector("#productTemplate"),
};

const formatPrice = (value, currency = "BRL") =>
  new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency,
  }).format(value);

const normalize = (value = "") =>
  String(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();

function filteredProducts() {
  if (!state.data) return [];

  const query = normalize(state.query);

  return state.data.products
    .filter((product) => product.active !== false)
    .filter((product) => {
      if (!query) return true;

      const haystack = normalize(
        [
          product.code,
          product.product_id,
          product.title,
          product.short_description,
          product.ml_public_id,
          ...(product.badges || []),
        ].join(" ")
      );

      return haystack.includes(query);
    })
    .sort((a, b) => Number(Boolean(b.featured)) - Number(Boolean(a.featured)));
}

function render() {
  const products = filteredProducts();

  elements.productGrid.innerHTML = "";
  elements.productCount.textContent =
    products.length === 1 ? "1 produto" : `${products.length} produtos`;
  elements.emptyState.classList.toggle("hidden", products.length > 0);

  products.forEach((product) => {
    const fragment = elements.productTemplate.content.cloneNode(true);

    const card = fragment.querySelector(".product-card");
    const image = fragment.querySelector(".product-image");
    const placeholder = fragment.querySelector(".image-placeholder");
    const placeholderCode = fragment.querySelector(".placeholder-code");
    const code = fragment.querySelector(".product-code");
    const featured = fragment.querySelector(".featured-badge");
    const badges = fragment.querySelector(".badges");
    const title = fragment.querySelector(".product-title");
    const description = fragment.querySelector(".product-description");
    const price = fragment.querySelector(".product-price");
    const priceNote = fragment.querySelector(".price-note");
    const buyButton = fragment.querySelector(".buy-button");
    const copyButton = fragment.querySelector(".copy-code-button");
    const mlCode = fragment.querySelector(".ml-code");

    card.dataset.productCode = product.code;

    code.textContent = `PRODUTO ${product.code}`;
    placeholderCode.textContent = product.code;
    featured.classList.toggle("hidden", !product.featured);

    title.textContent = product.title;
    description.textContent = product.short_description || "";
    price.textContent = formatPrice(product.price, product.currency || "BRL");
    priceNote.textContent = product.price_checked_at
      ? `Atualizado em ${new Date(`${product.price_checked_at}T12:00:00`).toLocaleDateString("pt-BR")}`
      : "Preço sujeito a alteração";

    (product.badges || []).forEach((label) => {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = label;
      badges.appendChild(badge);
    });

    if (product.image_url) {
      image.src = product.image_url;
      image.alt = product.title;
      image.classList.remove("hidden");
      placeholder.classList.add("hidden");

      image.addEventListener(
        "error",
        () => {
          image.classList.add("hidden");
          placeholder.classList.remove("hidden");
        },
        { once: true }
      );
    }

    buyButton.href = product.affiliate_url;
    buyButton.dataset.code = product.code;

    buyButton.addEventListener("click", () => {
      console.info("outbound_click", {
        code: product.code,
        product_id: product.product_id,
        destination: product.affiliate_url,
        timestamp: new Date().toISOString(),
      });
    });

    mlCode.textContent = product.ml_public_id || "—";

    copyButton.addEventListener("click", async () => {
      const value = product.ml_public_id;

      if (!value) return;

      try {
        await navigator.clipboard.writeText(value);
        copyButton.classList.add("copied");

        const label = copyButton.querySelector("span");
        const previous = label.textContent;
        label.textContent = "Código copiado ✓";

        window.setTimeout(() => {
          label.textContent = previous;
          copyButton.classList.remove("copied");
        }, 1700);
      } catch {
        window.prompt("Copie o código:", value);
      }
    });

    elements.productGrid.appendChild(fragment);
  });
}

async function bootstrap() {
  try {
    const response = await fetch("./products.json", {
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error(`products.json: HTTP ${response.status}`);
    }

    state.data = await response.json();

    const brand = state.data.brand || {};
    elements.brandName.textContent = brand.name || "Precisou e nem sabia";
    elements.brandSubtitle.textContent =
      brand.subtitle || "Produtos úteis que valem uma olhada";

    render();
  } catch (error) {
    console.error(error);
    elements.productGrid.innerHTML = `
      <div class="empty-state">
        <h3>Não foi possível carregar a vitrine.</h3>
        <p>Confira se products.json está disponível no mesmo diretório.</p>
      </div>
    `;
    elements.productCount.textContent = "erro";
  }
}

elements.searchInput.addEventListener("input", (event) => {
  state.query = event.target.value;
  render();
});

bootstrap();
