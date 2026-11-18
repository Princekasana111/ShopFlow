from django.urls import path

from . import views

urlpatterns = [
    path("status/", views.StatusView.as_view(), name="ai-status"),
    path("search/", views.SearchView.as_view(), name="ai-search"),
    path("search/explain/", views.SearchExplainView.as_view(), name="ai-search-explain"),
    path("ask/", views.AskView.as_view(), name="ai-ask"),
    path("products/<int:product_id>/similar/", views.SimilarProductsView.as_view(), name="ai-similar"),
    path("products/<int:product_id>/review-insights/", views.ReviewInsightsView.as_view(), name="ai-review-insights"),
    path("assistant/chat/", views.AssistantChatView.as_view(), name="ai-chat"),
    path("assistant/sessions/", views.ChatSessionListView.as_view(), name="ai-sessions"),
    path("assistant/sessions/<uuid:session_id>/", views.ChatSessionDetailView.as_view(), name="ai-session-detail"),
    path("planner/", views.PlannerView.as_view(), name="ai-planner"),
    path("visual-search/", views.VisualSearchView.as_view(), name="ai-visual-search"),
    path("products/<int:product_id>/ask/", views.ProductQuestionView.as_view(), name="ai-product-ask"),
    path("products/<int:product_id>/complete-the-kit/", views.CompleteTheKitView.as_view(), name="ai-complete-kit"),
    path("purchase-check/", views.PurchaseCheckView.as_view(), name="ai-purchase-check"),
    path("owned/", views.OwnedView.as_view(), name="ai-owned"),
    path("offers/", views.OffersView.as_view(), name="ai-offers"),
    path("offers/<int:offer_id>/messages/", views.OfferMessageView.as_view(), name="ai-offer-message"),
    path("offers/<int:offer_id>/accept/", views.AcceptOfferView.as_view(), name="ai-offer-accept"),
    path("offers/<int:offer_id>/reopen/", views.ReopenOfferView.as_view(), name="ai-offer-reopen"),
    path("offers/<int:offer_id>/drop/", views.DropOfferView.as_view(), name="ai-offer-drop"),
    path("products/<int:product_id>/listing-check/", views.ListingCheckView.as_view(), name="ai-listing-check"),
    path("products/<int:product_id>/fit/", views.FitView.as_view(), name="ai-fit"),
    path("listing-issues/", views.ListingIssuesView.as_view(), name="ai-listing-issues"),
    path("copywriter/", views.CopywriterView.as_view(), name="ai-copywriter"),
    path("metrics/", views.MetricsView.as_view(), name="ai-metrics"),
    path("local-model/", views.LocalModelView.as_view(), name="ai-local-model"),
]
