import { Link } from "react-router-dom";
import { rupees } from "../api.js";
import ProductArt from "./ProductArt.jsx";
import { Rating } from "./ui.jsx";

export default function ProductCard({ product, match }) {
  const category = product.category?.name || product.category;
  return (
    <Link to={`/products/${product.id}`} className="pcard">
      <div className="art-wrap">
        <ProductArt product={product} />
        <div className="overlay">
          <span className="tag">{category}</span>
          {product.stock === 0 ? <span className="tag out">Out of stock</span> : product.stock <= 12 ? <span className="tag low">Only {product.stock} left</span> : null}
        </div>
      </div>
      <div className="pcard-body">
        <span className="brand-line">{product.brand}</span>
        <span className="name">{product.name}</span>
        {match && "clip_rank" in match && (
          <span className="match" title="Where this result came from in photo search">
            <span className={match.clip_rank ? "hit" : ""}>{match.clip_rank ? `Visual #${match.clip_rank}` : "No visual match"}</span>
            {match.text_rank && <span className="hit">Claude #{match.text_rank}</span>}
          </span>
        )}
        {match && "vector_rank" in match && (
          <span className="match" title="Where this result came from in hybrid search">
            <span className={match.vector_rank ? "hit" : ""}>{match.vector_rank ? `Semantic #${match.vector_rank}` : "No semantic match"}</span>
            <span className={match.keyword_rank ? "hit" : ""}>{match.keyword_rank ? `Keyword #${match.keyword_rank}` : "No keyword match"}</span>
          </span>
        )}
        <div className="foot">
          <span className="price">{rupees(product.price)}</span>
          <Rating value={product.avg_rating} count={product.review_count} />
        </div>
      </div>
    </Link>
  );
}
