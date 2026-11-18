// Product art: a CC0 product photo when one exists (PRODUCT_IMAGES, keyed by product name), otherwise
// an illustrated tile: the category colour with an icon picked from the name. A product added in
// the admin, or renamed, has no photo yet, so it still gets a sensible illustrated tile.
import {
  Activity, BatteryCharging, BedDouble, Bike, Blinds, BookOpen, Bot, Brain, Briefcase, ChefHat, CloudRain, Code,
  Coffee, CookingPot, Cpu, Dumbbell, Feather, Footprints, GlassWater, Headphones, HeartPulse, House, Keyboard,
  LampDesk, Leaf, Microwave, Monitor, Moon, Mountain, Mouse, PersonStanding, PlugZap, Rocket, Shirt, Snowflake,
  Sparkles, Speaker, Sun, Timer, Trophy, Umbrella, UtensilsCrossed, Volleyball, Wallet, Watch, Waves, Webcam, Zap,
} from "lucide-react";
import { PRODUCT_IMAGES } from "./productImages.js";

// `image` is a CC0 photo for the category tile (public/categories/, credits in docs/IMAGE_CREDITS.md).
export const CATEGORIES = {
  electronics: { name: "Electronics", color: "#2f6bd8", icon: Cpu, image: "/categories/electronics.webp" },
  footwear: { name: "Footwear", color: "#d9581f", icon: Footprints, image: "/categories/footwear.webp" },
  clothing: { name: "Clothing", color: "#c43c78", icon: Shirt, image: "/categories/clothing.webp" },
  "home-kitchen": { name: "Home & Kitchen", color: "#11907f", icon: House, image: "/categories/home-kitchen.webp" },
  books: { name: "Books", color: "#b8740c", icon: BookOpen, image: "/categories/books.webp" },
  "sports-fitness": { name: "Sports & Fitness", color: "#3f9a3a", icon: Dumbbell, image: "/categories/sports-fitness.webp" },
};
const SLUG_BY_NAME = Object.fromEntries(Object.entries(CATEGORIES).map(([slug, c]) => [c.name, slug]));

const RULES = [
  [/headphone|earbud|earphone/i, Headphones], [/speaker/i, Speaker], [/power ?bank/i, BatteryCharging],
  [/charger/i, PlugZap], [/watch/i, Watch], [/keyboard/i, Keyboard], [/mouse/i, Mouse], [/webcam|camera/i, Webcam],
  [/monitor/i, Monitor], [/hiking|boots/i, Mountain], [/aqua|waterproof running/i, CloudRain], [/sandal/i, Sun],
  [/slipper/i, Moon], [/oxford|formal/i, Briefcase], [/flip-?flop/i, Waves], [/light-up|kids/i, Sparkles],
  [/shoe|sneaker/i, Footprints], [/puffer|hoodie|fleece/i, Snowflake], [/rain jacket/i, Umbrella], [/kurta/i, Sparkles],
  [/socks/i, Mountain], [/legging|yoga/i, PersonStanding], [/flask|mug/i, Coffee], [/kettle/i, Zap],
  [/frying pan|cookware/i, CookingPot], [/air fryer/i, Microwave], [/knife|cutting board/i, UtensilsCrossed],
  [/curtain/i, Blinds], [/bedsheet|pillow/i, BedDouble], [/lamp/i, LampDesk], [/bottle/i, GlassWater],
  [/python|coding|programming/i, Code], [/machine learning/i, Brain], [/\bllm\b/i, Bot], [/space|atlas/i, Rocket],
  [/money|finance/i, Wallet], [/cooking|recipe/i, ChefHat], [/calm|meditation/i, Leaf], [/dumbbell/i, Dumbbell],
  [/resistance band/i, Activity], [/cricket|\bbat\b/i, Trophy], [/football/i, Volleyball],
  [/badminton|racket/i, Feather], [/skipping|rope/i, Timer], [/roller/i, HeartPulse], [/helmet|cycling/i, Bike],
];

export function categoryOf(product) {
  const c = product?.category;
  const slug = typeof c === "object" && c ? c.slug || SLUG_BY_NAME[c.name] : SLUG_BY_NAME[c] || c;
  return CATEGORIES[slug] ? slug : "electronics";
}

export function iconFor(product) {
  const name = product?.name || product?.product_name || "";
  const rule = RULES.find(([re]) => re.test(name));
  return rule ? rule[1] : CATEGORIES[categoryOf(product)].icon;
}

export default function ProductArt({ product, size = "md", className = "" }) {
  const color = CATEGORIES[categoryOf(product)].color;
  const photo = PRODUCT_IMAGES[product?.name || product?.product_name || ""];
  if (photo) {
    return (
      <div className={`art photo ${size === "sm" ? "sm" : ""} ${className}`} style={{ "--c": color }} aria-hidden="true">
        <img src={photo} alt="" width="800" height="600" loading="lazy" decoding="async" />
      </div>
    );
  }
  const Icon = iconFor(product);
  return (
    <div className={`art ${size === "sm" ? "sm" : ""} ${className}`} style={{ "--c": color }} aria-hidden="true">
      <Icon strokeWidth={1.6} />
    </div>
  );
}
