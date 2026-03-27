const state = {
  items: [],
  discovery: null,
  cart: [],
  couponCode: '',
  summary: null,
  staticMode: false,
};

const STATIC_SNACKS = [
  {
    id: 'seaweed_chips',
    name: '海盐海苔脆片',
    brand: '脆浪研究所',
    category: '脆片',
    flavors: ['海盐', '轻咸'],
    scene: '办公室解馋',
    healthy_label: '低负担',
    price: 12.9,
    list_price: 15.9,
    weight_grams: 55,
    rating: 4.8,
    monthly_sales: 3200,
    badges: ['爆款', '下午茶首选'],
    bundle_with: ['iced_oolong', 'mixed_nuts'],
    image_hint: 'crispy seaweed chips',
  },
  {
    id: 'mixed_nuts',
    name: '蜂蜜综合坚果杯',
    brand: '山野小仓',
    category: '坚果',
    flavors: ['蜂蜜', '轻甜'],
    scene: '健身加餐',
    healthy_label: '高蛋白',
    price: 18.5,
    list_price: 22.0,
    weight_grams: 80,
    rating: 4.9,
    monthly_sales: 2750,
    badges: ['高蛋白', '饱腹感强'],
    bundle_with: ['seaweed_chips', 'dried_mango'],
    image_hint: 'mixed nuts cup',
  },
  {
    id: 'dried_mango',
    name: '阳光芒果干',
    brand: '果真甜',
    category: '果干',
    flavors: ['芒果', '果香'],
    scene: '追剧分享',
    healthy_label: '真果肉',
    price: 16.8,
    list_price: 19.8,
    weight_grams: 90,
    rating: 4.7,
    monthly_sales: 1980,
    badges: ['真果肉', '追剧零嘴'],
    bundle_with: ['sparkling_water', 'mixed_nuts'],
    image_hint: 'dried mango strips',
  },
  {
    id: 'spicy_konjac',
    name: '麻辣魔芋爽',
    brand: '辣上瘾',
    category: '辣味',
    flavors: ['麻辣', '微甜'],
    scene: '夜宵放松',
    healthy_label: '低脂',
    price: 9.9,
    list_price: 12.9,
    weight_grams: 68,
    rating: 4.6,
    monthly_sales: 4100,
    badges: ['回购王', '夜宵搭子'],
    bundle_with: ['iced_oolong'],
    image_hint: 'spicy konjac snack',
  },
  {
    id: 'choco_cookies',
    name: '可可夹心曲奇',
    brand: '甜点小岛',
    category: '饼干',
    flavors: ['可可', '香甜'],
    scene: '送礼囤货',
    healthy_label: '满足感',
    price: 21.8,
    list_price: 25.8,
    weight_grams: 120,
    rating: 4.8,
    monthly_sales: 1680,
    badges: ['礼盒友好', '办公室分享'],
    bundle_with: ['sparkling_water'],
    image_hint: 'chocolate sandwich cookies',
  },
  {
    id: 'rice_cracker',
    name: '酱烤米饼组合',
    brand: '米香作坊',
    category: '米饼',
    flavors: ['酱香', '微辣'],
    scene: '家庭囤货',
    healthy_label: '非油炸',
    price: 14.6,
    list_price: 17.6,
    weight_grams: 100,
    rating: 4.5,
    monthly_sales: 1850,
    badges: ['家庭装', '非油炸'],
    bundle_with: ['sparkling_water', 'seaweed_chips'],
    image_hint: 'rice cracker assortment',
  },
  {
    id: 'iced_oolong',
    name: '冷泡乌龙茶',
    brand: '喝点清爽',
    category: '饮品',
    flavors: ['茶香', '清爽'],
    scene: '凑单免邮',
    healthy_label: '0糖',
    price: 6.5,
    list_price: 8.0,
    weight_grams: 500,
    rating: 4.7,
    monthly_sales: 5200,
    badges: ['凑单神器', '0糖'],
    bundle_with: ['spicy_konjac', 'seaweed_chips'],
    image_hint: 'iced oolong tea bottle',
  },
  {
    id: 'sparkling_water',
    name: '白桃气泡水',
    brand: '气泡实验室',
    category: '饮品',
    flavors: ['白桃', '清甜'],
    scene: '下午茶搭配',
    healthy_label: '轻负担',
    price: 7.8,
    list_price: 9.9,
    weight_grams: 480,
    rating: 4.6,
    monthly_sales: 2980,
    badges: ['搭配推荐', '下午茶'],
    bundle_with: ['dried_mango', 'choco_cookies'],
    image_hint: 'peach sparkling water',
  },
];

const STATIC_COUPONS = {
  SNACK10: { threshold: 59.0, discount: 10.0, label: '满59减10' },
  FREESHIP: { threshold: 39.0, discount: 6.0, label: '运费补贴券' },
};

const HEALTHY_TAGS = new Set(['低负担', '高蛋白', '真果肉', '非油炸', '0糖', '轻负担', '低脂']);

const elements = {
  heroCard: document.getElementById('heroCard'),
  productGrid: document.getElementById('productGrid'),
  cartItems: document.getElementById('cartItems'),
  cartSummary: document.getElementById('cartSummary'),
  cartCount: document.getElementById('cartCount'),
  recommendations: document.getElementById('recommendations'),
  couponStrip: document.getElementById('couponStrip'),
  queryInput: document.getElementById('queryInput'),
  categorySelect: document.getElementById('categorySelect'),
  sceneSelect: document.getElementById('sceneSelect'),
  sortSelect: document.getElementById('sortSelect'),
  maxPriceInput: document.getElementById('maxPriceInput'),
  maxPriceValue: document.getElementById('maxPriceValue'),
  healthyOnlyInput: document.getElementById('healthyOnlyInput'),
  reloadButton: document.getElementById('reloadButton'),
};

function serializeItem(item) {
  return {
    ...item,
    discount: Number((item.list_price - item.price).toFixed(2)),
    price_label: `${item.price.toFixed(1)} 元`,
    list_price_label: `${item.list_price.toFixed(1)} 元`,
  };
}

function staticFilterSnacks(options = {}) {
  const {
    query = '',
    category = '',
    flavor = '',
    scene = '',
    maxPrice = null,
    healthyOnly = false,
    sortBy = 'smart',
  } = options;
  const queryLower = query.trim().toLowerCase();
  const items = STATIC_SNACKS.filter((item) => {
    if (queryLower && !`${item.name}${item.brand}${item.category}`.toLowerCase().includes(queryLower)) {
      return false;
    }
    if (category && item.category !== category) {
      return false;
    }
    if (flavor && !item.flavors.includes(flavor)) {
      return false;
    }
    if (scene && item.scene !== scene) {
      return false;
    }
    if (maxPrice !== null && item.price > maxPrice) {
      return false;
    }
    if (healthyOnly && !HEALTHY_TAGS.has(item.healthy_label)) {
      return false;
    }
    return true;
  });

  items.sort((left, right) => {
    if (sortBy === 'price') {
      return left.price - right.price || right.rating - left.rating;
    }
    if (sortBy === 'rating') {
      return right.rating - left.rating || right.monthly_sales - left.monthly_sales;
    }
    const leftScore = left.rating * 10 + left.monthly_sales / 500;
    const rightScore = right.rating * 10 + right.monthly_sales / 500;
    return rightScore - leftScore || left.price - right.price;
  });
  return items.map(serializeItem);
}

function staticRecommendations(cartIds) {
  const current = new Set(cartIds);
  const recommendations = [];
  for (const item of STATIC_SNACKS) {
    if (!current.has(item.id)) {
      continue;
    }
    for (const candidate of STATIC_SNACKS) {
      if (current.has(candidate.id) || recommendations.some((entry) => entry.id === candidate.id)) {
        continue;
      }
      if (item.bundle_with.includes(candidate.id)) {
        recommendations.push(candidate);
      }
    }
  }
  if (!recommendations.length) {
    recommendations.push(...[...STATIC_SNACKS].sort((left, right) => right.rating - left.rating || left.price - right.price).slice(0, 3));
  }
  return recommendations.slice(0, 4).map(serializeItem);
}

function staticDiscovery() {
  return {
    hero: {
      title: '今晚追剧零食，一站买齐',
      subtitle: '按口味、预算、场景快速挑选，自动推荐凑单与优惠组合。',
      cta: '30 分钟内搞定本周零食清单',
    },
    best_sellers: staticFilterSnacks({ sortBy: 'smart' }).slice(0, 4),
    healthy_picks: staticFilterSnacks({ healthyOnly: true, sortBy: 'rating' }).slice(0, 4),
    cart_boosters: STATIC_SNACKS.filter((item) => item.badges.includes('凑单神器') || item.price <= 10).slice(0, 4).map(serializeItem),
    coupon_cards: Object.entries(STATIC_COUPONS).map(([code, meta]) => ({ code, ...meta })),
  };
}

function staticSummary(lines, couponCode) {
  const items = [];
  let subtotal = 0;
  let bundleDiscount = 0;
  const cartIds = [];

  for (const line of lines) {
    const snack = STATIC_SNACKS.find((item) => item.id === String(line.id || '').trim());
    if (!snack) {
      continue;
    }
    const qty = Math.max(1, Number(line.qty || 1));
    const lineTotal = snack.price * qty;
    subtotal += lineTotal;
    cartIds.push(snack.id);
    items.push({
      id: snack.id,
      name: snack.name,
      qty,
      unit_price: snack.price,
      line_total: Number(lineTotal.toFixed(2)),
    });
  }

  if (cartIds.includes('seaweed_chips') && cartIds.includes('iced_oolong')) {
    bundleDiscount += 3;
  }
  if (cartIds.includes('mixed_nuts') && cartIds.includes('dried_mango')) {
    bundleDiscount += 4;
  }

  const normalizedCode = String(couponCode || '').trim().toUpperCase();
  const coupon = STATIC_COUPONS[normalizedCode];
  let couponDiscount = 0;
  let appliedCoupon = null;
  if (coupon && subtotal >= coupon.threshold) {
    couponDiscount = coupon.discount;
    appliedCoupon = { code: normalizedCode, ...coupon };
  }

  const shippingFee = subtotal - bundleDiscount >= 49 ? 0 : 8;
  const total = Math.max(0, subtotal - bundleDiscount - couponDiscount + shippingFee);
  const nudges = [];
  if (subtotal < 49) {
    nudges.push(`再买 ${(49 - subtotal).toFixed(1)} 元即可免邮`);
  }
  if (subtotal < 59) {
    nudges.push(`再买 ${(59 - subtotal).toFixed(1)} 元可用满59减10优惠`);
  }
  if (!cartIds.length) {
    nudges.push('先把喜欢的零食加入购物车，系统会自动推荐凑单组合');
  }

  return {
    items,
    subtotal: Number(subtotal.toFixed(2)),
    bundle_discount: Number(bundleDiscount.toFixed(2)),
    coupon_discount: Number(couponDiscount.toFixed(2)),
    shipping_fee: Number(shippingFee.toFixed(2)),
    total: Number(total.toFixed(2)),
    reward_points: Math.floor(total),
    applied_coupon: appliedCoupon,
    nudges,
    recommendations: staticRecommendations(cartIds),
  };
}

async function fetchJson(url, options = {}) {
  try {
    const response = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    return response.json();
  } catch (error) {
    state.staticMode = true;
    if (url.includes('/api/discovery')) {
      return staticDiscovery();
    }
    if (url.includes('/api/snacks')) {
      const requestUrl = new URL(url, window.location.href);
      return {
        items: staticFilterSnacks({
          query: requestUrl.searchParams.get('query') || '',
          category: requestUrl.searchParams.get('category') || '',
          scene: requestUrl.searchParams.get('scene') || '',
          maxPrice: Number(requestUrl.searchParams.get('max_price') || 0) || null,
          healthyOnly: requestUrl.searchParams.get('healthy_only') === 'true',
          sortBy: requestUrl.searchParams.get('sort_by') || 'smart',
        }),
      };
    }
    if (url.includes('/api/cart/summary')) {
      const body = JSON.parse(options.body || '{}');
      return staticSummary(body.lines || [], body.coupon_code || '');
    }
    throw error;
  }
}

function productCard(item) {
  const badges = item.badges.map((badge) => `<span class="badge">${badge}</span>`).join('');
  return `
    <article class="product-card">
      <div class="product-copy">
        <p class="category">${item.category} · ${item.scene}</p>
        <h3>${item.name}</h3>
        <p class="meta">${item.brand} · ${item.healthy_label}</p>
        <p class="flavors">口味：${item.flavors.join(' / ')}</p>
        <div class="badge-row">${badges}</div>
      </div>
      <div class="price-row">
        <div>
          <strong>${item.price_label}</strong>
          <span class="list-price">${item.list_price_label}</span>
        </div>
        <button data-id="${item.id}" class="primary-button add-button">加入购物车</button>
      </div>
    </article>
  `;
}

function renderHero() {
  const hero = state.discovery?.hero;
  if (!hero) {
    return;
  }
  elements.heroCard.innerHTML = `
    <div>
      <p class="eyebrow">${state.staticMode ? `${hero.cta} · 静态演示模式` : hero.cta}</p>
      <h2>${hero.title}</h2>
      <p>${hero.subtitle}</p>
    </div>
    <div class="hero-highlights">
      <div>
        <strong>智能凑单</strong>
        <span>自动提醒免邮门槛和组合优惠</span>
      </div>
      <div>
        <strong>场景选购</strong>
        <span>追剧、办公室、健身加餐一键切换</span>
      </div>
      <div>
        <strong>积分复购</strong>
        <span>结算页同步展示积分和下次回购激励</span>
      </div>
    </div>
  `;
}

function renderCoupons() {
  const coupons = state.discovery?.coupon_cards ?? [];
  elements.couponStrip.innerHTML = coupons
    .map(
      (coupon) => `
        <button class="coupon-chip ${state.couponCode === coupon.code ? 'active' : ''}" data-coupon="${coupon.code}">
          <strong>${coupon.label}</strong>
          <span>${coupon.code}</span>
        </button>
      `,
    )
    .join('');
}

function renderProducts() {
  elements.productGrid.innerHTML = state.items.map(productCard).join('');
}

function renderCart() {
  elements.cartCount.textContent = `${state.cart.reduce((sum, item) => sum + item.qty, 0)} 件`;
  if (!state.cart.length) {
    elements.cartItems.className = 'cart-items empty-state';
    elements.cartItems.textContent = '先把喜欢的零食加入购物车吧。';
    elements.cartSummary.innerHTML = '<p>系统会在这里计算优惠、免邮和积分。</p>';
    elements.recommendations.innerHTML = '';
    return;
  }

  elements.cartItems.className = 'cart-items';
  elements.cartItems.innerHTML = state.summary.items
    .map(
      (item) => `
        <div class="cart-item">
          <div>
            <strong>${item.name}</strong>
            <p>x${item.qty}</p>
          </div>
          <div class="cart-item-actions">
            <span>${item.line_total.toFixed(1)} 元</span>
            <button data-id="${item.id}" class="ghost-button minus-button">-1</button>
          </div>
        </div>
      `,
    )
    .join('');

  const couponLine = state.summary.applied_coupon
    ? `<p>优惠券：- ${state.summary.coupon_discount.toFixed(1)} 元（${state.summary.applied_coupon.label}）</p>`
    : '<p>优惠券：暂未满足门槛</p>';
  const nudgeLine = state.summary.nudges.map((line) => `<li>${line}</li>`).join('');
  elements.cartSummary.innerHTML = `
    <p>商品金额：${state.summary.subtotal.toFixed(1)} 元</p>
    <p>组合优惠：- ${state.summary.bundle_discount.toFixed(1)} 元</p>
    ${couponLine}
    <p>运费：${state.summary.shipping_fee.toFixed(1)} 元</p>
    <p class="summary-total">应付：${state.summary.total.toFixed(1)} 元</p>
    <p>本单可得积分：${state.summary.reward_points}</p>
    <ul class="nudge-list">${nudgeLine}</ul>
  `;

  elements.recommendations.innerHTML = state.summary.recommendations
    .map(
      (item) => `
        <button data-id="${item.id}" class="recommend-card add-button">
          <strong>${item.name}</strong>
          <span>${item.price_label}</span>
        </button>
      `,
    )
    .join('');
}

async function loadDiscovery() {
  state.discovery = await fetchJson('./api/discovery');
  renderHero();
  renderCoupons();
}

async function loadProducts() {
  const params = new URLSearchParams({
    query: elements.queryInput.value,
    category: elements.categorySelect.value,
    scene: elements.sceneSelect.value,
    sort_by: elements.sortSelect.value,
    max_price: elements.maxPriceInput.value,
    healthy_only: String(elements.healthyOnlyInput.checked),
  });
  const payload = await fetchJson(`./api/snacks?${params.toString()}`);
  state.items = payload.items;
  renderProducts();
}

async function refreshSummary() {
  state.summary = await fetchJson('./api/cart/summary', {
    method: 'POST',
    body: JSON.stringify({
      lines: state.cart,
      coupon_code: state.couponCode,
    }),
  });
  renderCart();
}

function addToCart(id) {
  const existing = state.cart.find((item) => item.id === id);
  if (existing) {
    existing.qty += 1;
  } else {
    state.cart.push({ id, qty: 1 });
  }
  refreshSummary();
}

function removeOne(id) {
  const existing = state.cart.find((item) => item.id === id);
  if (!existing) {
    return;
  }
  existing.qty -= 1;
  if (existing.qty <= 0) {
    state.cart = state.cart.filter((item) => item.id !== id);
  }
  refreshSummary();
}

function bindEvents() {
  document.body.addEventListener('click', (event) => {
    const target = event.target.closest('button');
    if (!target) {
      return;
    }
    if (target.classList.contains('add-button') && target.dataset.id) {
      addToCart(target.dataset.id);
    }
    if (target.classList.contains('minus-button') && target.dataset.id) {
      removeOne(target.dataset.id);
    }
    if (target.dataset.coupon) {
      state.couponCode = state.couponCode === target.dataset.coupon ? '' : target.dataset.coupon;
      renderCoupons();
      refreshSummary();
    }
  });

  [
    elements.queryInput,
    elements.categorySelect,
    elements.sceneSelect,
    elements.sortSelect,
    elements.healthyOnlyInput,
  ].forEach((element) => element.addEventListener('input', loadProducts));

  elements.maxPriceInput.addEventListener('input', () => {
    elements.maxPriceValue.textContent = `${elements.maxPriceInput.value} 元`;
    loadProducts();
  });
  elements.reloadButton.addEventListener('click', async () => {
    await loadDiscovery();
    await loadProducts();
    await refreshSummary();
  });
}

async function bootstrap() {
  bindEvents();
  await loadDiscovery();
  await loadProducts();
  await refreshSummary();
}

bootstrap().catch((error) => {
  elements.productGrid.innerHTML = `<p class="empty-state">加载失败：${error.message}</p>`;
});
