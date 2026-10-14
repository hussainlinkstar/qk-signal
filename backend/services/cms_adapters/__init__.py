from __future__ import annotations

import models

from .base_adapter import CMSAdapter
from .shopify_adapter import ShopifyAdapter
from .wordpress_adapter import WordPressAdapter


def get_cms_adapter(cms_connection: models.CMSConnection) -> CMSAdapter:
    cms_type = str(cms_connection.cms_type or "").strip().lower()
    if cms_type == "wordpress":
        return WordPressAdapter(cms_connection)
    if cms_type == "shopify":
        return ShopifyAdapter(cms_connection)
    raise ValueError(f"Unsupported CMS type: {cms_connection.cms_type}")
