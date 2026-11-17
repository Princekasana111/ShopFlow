// Illustrated product art: no stock photos, so each product gets a category-tinted tile with
// an icon picked from its name. New products added by an admin get a sensible icon too.
import {
  Activity, BatteryCharging, BedDouble, Bike, Blinds, BookOpen, Bot, Brain, Briefcase, ChefHat, CloudRain, Code,
  Coffee, CookingPot, Cpu, Dumbbell, Feather, Footprints, GlassWater, Headphones, HeartPulse, House, Keyboard,
  LampDesk, Leaf, Microwave, Monitor, Moon, Mountain, Mouse, PersonStanding, PlugZap, Rocket, Shirt, Snowflake,
  Sparkles, Speaker, Sun, Timer, Trophy, Umbrella, UtensilsCrossed, Volleyball, Wallet, Watch, Waves, Webcam, Zap,
} from "lucide-react";

export const CATEGORIES = {
  electronics: { name: "Electronics", color: "#4f46e5", icon: Cpu },
  footwear: { name: "Footwear", color: "#ea580c", icon: Footprints },
  clothing: { name: "Clothing", color: "#db2777", icon: Shirt },
  "home-kitchen": { name: "Home & Kitchen", color: "#0d9488", icon: House },
  books: { name: "Books", color: "#b45309", icon: BookOpen },
  "sports-fitness": { name: "Sports & Fitness", color: "#16a34a", icon: Dumbbell },
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
  const Icon = iconFor(product);
  const color = CATEGORIES[categoryOf(product)].color;
  return (
    <div className={`art ${size === "sm" ? "sm" : ""} ${className}`} style={{ "--c": color }} aria-hidden="true">
      <Icon strokeWidth={1.6} />
    </div>
  );
}
