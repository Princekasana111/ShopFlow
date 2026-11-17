from django.urls import path

from . import views

urlpatterns = [
    path("status/", views.StatusView.as_view(), name="ai-status"),
    path("search/", views.SearchView.as_view(), name="ai-search"),
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
    path("copywriter/", views.CopywriterView.as_view(), name="ai-copywriter"),
    path("metrics/", views.MetricsView.as_view(), name="ai-metrics"),
]
