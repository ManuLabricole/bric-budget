from django.shortcuts import redirect
from django.views.generic import TemplateView


class LandingView(TemplateView):
    template_name = "landing/index.html"

    def dispatch(self, request, *args, **kwargs):
        # Utilisateur déjà connecté → app directement, pas besoin de la landing.
        if request.user.is_authenticated:
            return redirect("budget:index")
        return super().dispatch(request, *args, **kwargs)
