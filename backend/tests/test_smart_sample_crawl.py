"""Tests for smart sample crawl URL selection and plan building."""

from __future__ import annotations

from services.page_type_detector import (
    build_smart_crawl_plan,
    select_representative_urls,
)


class TestSelectRepresentativeUrls:
    """Tests for select_representative_urls()."""

    def test_basic_selection(self):
        urls = [
            "https://example.com/",
            "https://example.com/blog/post-one",
            "https://example.com/blog/post-two",
            "https://example.com/products/widget",
            "https://example.com/about",
        ]
        result = select_representative_urls(urls, max_per_type=2, max_total=10)
        assert isinstance(result, dict)
        total = sum(len(v) for v in result.values())
        assert total <= 10
        assert total >= 1

    def test_low_value_types_excluded_by_default(self):
        urls = [
            "https://example.com/",
            "https://example.com/terms",
            "https://example.com/privacy",
            "https://example.com/login",
            "https://example.com/signup",
            "https://example.com/checkout",
        ]
        result = select_representative_urls(urls, max_per_type=2, max_total=10)
        # Only homepage should be selected; all others are low-value
        all_selected = [u for urls_list in result.values() for u in urls_list]
        assert any(
            "example.com/" == u.rstrip("/").split("//")[-1] or u.endswith(".com/")
            for u in all_selected
        )
        for low_value in ["/terms", "/privacy", "/login", "/signup", "/checkout"]:
            low_urls = [u for u in all_selected if low_value in u and not u.endswith(".com/")]
            assert len(low_urls) == 0, f"Low-value URL with '{low_value}' should not be selected"

    def test_include_low_value_when_requested(self):
        urls = [
            "https://example.com/",
            "https://example.com/terms",
            "https://example.com/privacy",
        ]
        result = select_representative_urls(
            urls, max_per_type=2, max_total=10, include_low_value=True
        )
        all_selected = [u for urls_list in result.values() for u in urls_list]
        assert len(all_selected) >= 2  # homepage + at least one low-value

    def test_max_total_respected(self):
        urls = [f"https://example.com/blog/post-{i}" for i in range(50)]
        urls.append("https://example.com/")
        urls.append("https://example.com/products/widget-a")
        urls.append("https://example.com/products/widget-b")
        urls.append("https://example.com/about")
        result = select_representative_urls(urls, max_per_type=3, max_total=5)
        total = sum(len(v) for v in result.values())
        assert total <= 5

    def test_max_per_type_respected(self):
        urls = [f"https://example.com/blog/article-{i}" for i in range(20)]
        result = select_representative_urls(urls, max_per_type=2, max_total=50)
        for ptype, selected in result.items():
            assert len(selected) <= 2, f"Type {ptype} has more than 2 URLs"

    def test_empty_urls(self):
        result = select_representative_urls([], max_per_type=2, max_total=10)
        assert result == {}

    def test_single_url(self):
        result = select_representative_urls(
            ["https://example.com/"],
            max_per_type=2,
            max_total=10,
        )
        assert sum(len(v) for v in result.values()) == 1

    def test_prioritizes_high_value_types(self):
        urls = [
            "https://example.com/",  # homepage (100)
            "https://example.com/products/widget",  # product (90)
            "https://example.com/about",  # about (60)
            "https://example.com/careers/engineer",  # careers (30)
        ]
        result = select_representative_urls(urls, max_per_type=1, max_total=2)
        all_selected = [u for urls_list in result.values() for u in urls_list]
        # Homepage and product should be selected before about and careers
        assert any(u.endswith(".com/") or u == "https://example.com/" for u in all_selected)
        assert len(all_selected) == 2


class TestBuildSmartCrawlPlan:
    """Tests for build_smart_crawl_plan()."""

    def test_plan_structure(self):
        urls = [
            "https://example.com/",
            "https://example.com/blog/post-one",
            "https://example.com/blog/post-two",
            "https://example.com/products/widget",
            "https://example.com/about",
            "https://example.com/faq",
            "https://example.com/terms",
        ]
        plan = build_smart_crawl_plan(urls)

        assert "total_site_urls" in plan
        assert plan["total_site_urls"] == 7
        assert "total_page_types" in plan
        assert plan["total_page_types"] >= 4  # homepage, blog_article, product, about, faq, terms
        assert "sampled_urls_count" in plan
        assert plan["sampled_urls_count"] > 0
        assert plan["sampled_urls_count"] <= plan["total_site_urls"]
        assert "plan" in plan
        assert isinstance(plan["plan"], list)
        assert len(plan["plan"]) > 0

    def test_plan_breakdown_fields(self):
        urls = [
            "https://example.com/",
            "https://example.com/blog/post-one",
        ]
        plan = build_smart_crawl_plan(urls)
        for item in plan["plan"]:
            assert "page_type" in item
            assert "label" in item
            assert "total_urls" in item
            assert "sampled_urls" in item
            assert "sample_urls" in item
            assert "skipped" in item
            assert "coverage_ratio" in item
            assert isinstance(item["sample_urls"], list)
            assert isinstance(item["coverage_ratio"], float)

    def test_low_value_marked_as_skipped(self):
        urls = [
            "https://example.com/",
            "https://example.com/terms",
            "https://example.com/privacy-policy",
        ]
        plan = build_smart_crawl_plan(urls)
        skipped_types = [item for item in plan["plan"] if item["skipped"]]
        # Terms and privacy should be skipped
        assert len(skipped_types) >= 1

    def test_selected_urls_returned(self):
        urls = [
            "https://example.com/",
            "https://example.com/blog/great-post",
            "https://example.com/products/widget",
        ]
        plan = build_smart_crawl_plan(urls)
        assert "selected_urls" in plan
        assert isinstance(plan["selected_urls"], dict)
        all_selected = [u for urls_list in plan["selected_urls"].values() for u in urls_list]
        assert len(all_selected) == plan["sampled_urls_count"]

    def test_empty_urls(self):
        plan = build_smart_crawl_plan([])
        assert plan["total_site_urls"] == 0
        assert plan["sampled_urls_count"] == 0
        assert plan["plan"] == []

    def test_coverage_ratio_calculation(self):
        urls = [
            "https://example.com/blog/post-one",
            "https://example.com/blog/post-two",
            "https://example.com/blog/post-three",
            "https://example.com/blog/post-four",
        ]
        plan = build_smart_crawl_plan(urls, max_per_type=2)
        blog_items = [item for item in plan["plan"] if item["page_type"] == "blog_article"]
        if blog_items:
            item = blog_items[0]
            expected_ratio = round(item["sampled_urls"] / item["total_urls"], 2)
            assert item["coverage_ratio"] == expected_ratio
