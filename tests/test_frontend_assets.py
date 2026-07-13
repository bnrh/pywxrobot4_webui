from server.frontend_assets import clear_frontend_asset_cache, render_frontend_index_html, resolve_frontend_asset_hrefs


def test_resolve_frontend_asset_hrefs_prefers_dist_when_present() -> None:
    clear_frontend_asset_cache()
    css_href, js_href = resolve_frontend_asset_hrefs()
    assert css_href.startswith("/static/")
    assert js_href.startswith("/static/")
    assert js_href.endswith(".js")
    assert css_href.endswith(".css") or ".css" in css_href


def test_render_frontend_index_html_rewrites_assets() -> None:
    clear_frontend_asset_cache()
    html = render_frontend_index_html()
    assert 'rel="stylesheet"' in html
    assert 'type="module"' in html
    assert "nav-tab" in html
    css_href, js_href = resolve_frontend_asset_hrefs()
    assert css_href in html
    assert js_href in html
