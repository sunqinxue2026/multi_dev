from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class SnackItem:
    id: str
    name: str
    brand: str
    category: str
    flavors: tuple[str, ...]
    scene: str
    healthy_label: str
    price: float
    list_price: float
    weight_grams: int
    rating: float
    monthly_sales: int
    badges: tuple[str, ...]
    bundle_with: tuple[str, ...]
    image_hint: str


SNACKS: tuple[SnackItem, ...] = (
    SnackItem(
        id="seaweed_chips",
        name="海盐海苔脆片",
        brand="脆浪研究所",
        category="脆片",
        flavors=("海盐", "轻咸"),
        scene="办公室解馋",
        healthy_label="低负担",
        price=12.9,
        list_price=15.9,
        weight_grams=55,
        rating=4.8,
        monthly_sales=3200,
        badges=("爆款", "下午茶首选"),
        bundle_with=("iced_oolong", "mixed_nuts"),
        image_hint="crispy seaweed chips",
    ),
    SnackItem(
        id="mixed_nuts",
        name="蜂蜜综合坚果杯",
        brand="山野小仓",
        category="坚果",
        flavors=("蜂蜜", "轻甜"),
        scene="健身加餐",
        healthy_label="高蛋白",
        price=18.5,
        list_price=22.0,
        weight_grams=80,
        rating=4.9,
        monthly_sales=2750,
        badges=("高蛋白", "饱腹感强"),
        bundle_with=("seaweed_chips", "dried_mango"),
        image_hint="mixed nuts cup",
    ),
    SnackItem(
        id="dried_mango",
        name="阳光芒果干",
        brand="果真甜",
        category="果干",
        flavors=("芒果", "果香"),
        scene="追剧分享",
        healthy_label="真果肉",
        price=16.8,
        list_price=19.8,
        weight_grams=90,
        rating=4.7,
        monthly_sales=1980,
        badges=("真果肉", "追剧零嘴"),
        bundle_with=("sparkling_water", "mixed_nuts"),
        image_hint="dried mango strips",
    ),
    SnackItem(
        id="spicy_konjac",
        name="麻辣魔芋爽",
        brand="辣上瘾",
        category="辣味",
        flavors=("麻辣", "微甜"),
        scene="夜宵放松",
        healthy_label="低脂",
        price=9.9,
        list_price=12.9,
        weight_grams=68,
        rating=4.6,
        monthly_sales=4100,
        badges=("回购王", "夜宵搭子"),
        bundle_with=("iced_oolong",),
        image_hint="spicy konjac snack",
    ),
    SnackItem(
        id="choco_cookies",
        name="可可夹心曲奇",
        brand="甜点小岛",
        category="饼干",
        flavors=("可可", "香甜"),
        scene="送礼囤货",
        healthy_label="满足感",
        price=21.8,
        list_price=25.8,
        weight_grams=120,
        rating=4.8,
        monthly_sales=1680,
        badges=("礼盒友好", "办公室分享"),
        bundle_with=("sparkling_water",),
        image_hint="chocolate sandwich cookies",
    ),
    SnackItem(
        id="rice_cracker",
        name="酱烤米饼组合",
        brand="米香作坊",
        category="米饼",
        flavors=("酱香", "微辣"),
        scene="家庭囤货",
        healthy_label="非油炸",
        price=14.6,
        list_price=17.6,
        weight_grams=100,
        rating=4.5,
        monthly_sales=1850,
        badges=("家庭装", "非油炸"),
        bundle_with=("sparkling_water", "seaweed_chips"),
        image_hint="rice cracker assortment",
    ),
    SnackItem(
        id="iced_oolong",
        name="冷泡乌龙茶",
        brand="喝点清爽",
        category="饮品",
        flavors=("茶香", "清爽"),
        scene="凑单免邮",
        healthy_label="0糖",
        price=6.5,
        list_price=8.0,
        weight_grams=500,
        rating=4.7,
        monthly_sales=5200,
        badges=("凑单神器", "0糖"),
        bundle_with=("spicy_konjac", "seaweed_chips"),
        image_hint="iced oolong tea bottle",
    ),
    SnackItem(
        id="sparkling_water",
        name="白桃气泡水",
        brand="气泡实验室",
        category="饮品",
        flavors=("白桃", "清甜"),
        scene="下午茶搭配",
        healthy_label="轻负担",
        price=7.8,
        list_price=9.9,
        weight_grams=480,
        rating=4.6,
        monthly_sales=2980,
        badges=("搭配推荐", "下午茶"),
        bundle_with=("dried_mango", "choco_cookies"),
        image_hint="peach sparkling water",
    ),
)

COUPONS = {
    "SNACK10": {"threshold": 59.0, "discount": 10.0, "label": "满59减10"},
    "FREESHIP": {"threshold": 39.0, "discount": 6.0, "label": "运费补贴券"},
}


def _serialize(item: SnackItem) -> dict[str, object]:
    payload = asdict(item)
    payload["discount"] = round(item.list_price - item.price, 2)
    payload["price_label"] = f"{item.price:.1f} 元"
    payload["list_price_label"] = f"{item.list_price:.1f} 元"
    return payload


def all_snacks() -> list[dict[str, object]]:
    return [_serialize(item) for item in SNACKS]


def filter_snacks(
    query: str = "",
    category: str = "",
    flavor: str = "",
    scene: str = "",
    max_price: float | None = None,
    healthy_only: bool = False,
    sort_by: str = "smart",
) -> list[dict[str, object]]:
    query_lower = query.strip().lower()
    category = category.strip()
    flavor = flavor.strip()
    scene = scene.strip()

    filtered: list[SnackItem] = []
    for item in SNACKS:
        if query_lower and query_lower not in f"{item.name}{item.brand}{item.category}".lower():
            continue
        if category and item.category != category:
            continue
        if flavor and flavor not in item.flavors:
            continue
        if scene and item.scene != scene:
            continue
        if max_price is not None and item.price > max_price:
            continue
        if healthy_only and item.healthy_label not in {"低负担", "高蛋白", "真果肉", "非油炸", "0糖", "轻负担", "低脂"}:
            continue
        filtered.append(item)

    if sort_by == "price":
        filtered.sort(key=lambda item: (item.price, -item.rating))
    elif sort_by == "rating":
        filtered.sort(key=lambda item: (-item.rating, -item.monthly_sales))
    else:
        filtered.sort(
            key=lambda item: (
                -(item.rating * 10 + item.monthly_sales / 500),
                item.price,
            )
        )

    return [_serialize(item) for item in filtered]


def discovery_sections() -> dict[str, object]:
    best_sellers = filter_snacks(sort_by="smart")[:4]
    healthy_picks = filter_snacks(healthy_only=True, sort_by="rating")[:4]
    cart_boosters = [item for item in all_snacks() if "凑单神器" in item["badges"] or item["price"] <= 10]
    return {
        "hero": {
            "title": "今晚追剧零食，一站买齐",
            "subtitle": "按口味、预算、场景快速挑选，自动推荐凑单与优惠组合。",
            "cta": "30 分钟内搞定本周零食清单",
        },
        "best_sellers": best_sellers,
        "healthy_picks": healthy_picks,
        "cart_boosters": cart_boosters[:4],
        "coupon_cards": [
            {"code": code, **meta} for code, meta in COUPONS.items()
        ],
    }


def cart_recommendations(cart_ids: list[str]) -> list[dict[str, object]]:
    current = {item.id for item in SNACKS if item.id in cart_ids}
    recommendations: list[SnackItem] = []
    for item in SNACKS:
        if item.id not in current:
            continue
        for candidate in SNACKS:
            if candidate.id in current or candidate.id in {picked.id for picked in recommendations}:
                continue
            if candidate.id in item.bundle_with:
                recommendations.append(candidate)
    if not recommendations:
        recommendations = sorted(SNACKS, key=lambda item: (-item.rating, item.price))[:3]
    return [_serialize(item) for item in recommendations[:4]]


def checkout_summary(lines: list[dict[str, int]], coupon_code: str | None = None) -> dict[str, object]:
    items = []
    subtotal = 0.0
    bundle_discount = 0.0
    cart_ids: list[str] = []

    for line in lines:
        snack_id = str(line.get("id", "")).strip()
        qty = max(1, int(line.get("qty", 1)))
        snack = next((item for item in SNACKS if item.id == snack_id), None)
        if snack is None:
            continue
        line_total = snack.price * qty
        subtotal += line_total
        cart_ids.append(snack.id)
        items.append(
            {
                "id": snack.id,
                "name": snack.name,
                "qty": qty,
                "unit_price": snack.price,
                "line_total": round(line_total, 2),
            }
        )

    if {"seaweed_chips", "iced_oolong"}.issubset(set(cart_ids)):
        bundle_discount += 3.0
    if {"mixed_nuts", "dried_mango"}.issubset(set(cart_ids)):
        bundle_discount += 4.0

    coupon = COUPONS.get((coupon_code or "").strip().upper())
    coupon_discount = 0.0
    applied_coupon = None
    if coupon and subtotal >= coupon["threshold"]:
        coupon_discount = float(coupon["discount"])
        applied_coupon = {"code": (coupon_code or "").upper(), **coupon}

    shipping_fee = 0.0 if subtotal - bundle_discount >= 49 else 8.0
    total = max(0.0, subtotal - bundle_discount - coupon_discount + shipping_fee)
    reward_points = int(total)

    nudges = []
    if subtotal < 49:
        nudges.append(f"再买 {49 - subtotal:.1f} 元即可免邮")
    if subtotal < 59:
        nudges.append(f"再买 {59 - subtotal:.1f} 元可用满59减10优惠")
    if not cart_ids:
        nudges.append("先把喜欢的零食加入购物车，系统会自动推荐凑单组合")

    return {
        "items": items,
        "subtotal": round(subtotal, 2),
        "bundle_discount": round(bundle_discount, 2),
        "coupon_discount": round(coupon_discount, 2),
        "shipping_fee": round(shipping_fee, 2),
        "total": round(total, 2),
        "reward_points": reward_points,
        "applied_coupon": applied_coupon,
        "nudges": nudges,
        "recommendations": cart_recommendations(cart_ids),
    }
