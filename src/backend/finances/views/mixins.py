from django.contrib.auth.mixins import LoginRequiredMixin


class HtmxMixin:
    """Return fragment template for HTMX requests, full page otherwise."""

    template_name = ""
    htmx_template_name = ""

    def get_template_names(self):
        if self.request.htmx:
            return [self.htmx_template_name]
        return [self.template_name]


class HtmxLoginRequiredMixin(LoginRequiredMixin, HtmxMixin):
    """Combines login requirement with HTMX template switching."""

    pass
