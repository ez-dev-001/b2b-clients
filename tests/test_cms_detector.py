import pytest
from src.services.cms_detector import check_cms


class TestInputEdgeCases:
    def test_none_input(self):
        assert check_cms(None) == "No Website"

    def test_empty_string(self):
        assert check_cms("") == "No Website"

    def test_whitespace_only(self):
        assert check_cms("   ") == "No Website"


class TestSocialMedia:
    """Social media URLs should be detected without making HTTP requests."""

    def test_instagram(self):
        assert check_cms("https://www.instagram.com/flower_shop") == "Social Media"

    def test_facebook(self):
        assert check_cms("https://facebook.com/my.shop") == "Social Media"

    def test_telegram(self):
        assert check_cms("https://t.me/my_channel") == "Social Media"

    def test_tiktok(self):
        assert check_cms("https://tiktok.com/@shop") == "Social Media"

    def test_linktree(self):
        assert check_cms("https://linktr.ee/myshop") == "Social Media"


class TestRealSites:
    """Light integration tests against known CMS sites."""

    def test_tilda_site(self):
        result = check_cms("https://tilda.cc")
        assert result == "Tilda"

    def test_wix_site(self):
        # Use Wix template site which reliably contains Wix signatures
        result = check_cms("https://www.wix.com/website/templates")
        assert result == "Wix"

    def test_wordpress_site(self):
        # wordpress.org uses WordPress itself
        result = check_cms("https://wordpress.org")
        assert result == "WordPress"

    def test_unreachable_site(self):
        result = check_cms("https://this-domain-does-not-exist-999.com")
        assert result in ("Error/Unreachable", "Error/Timeout")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])