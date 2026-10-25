include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-alwayroute-external
PKG_VERSION:=1.0.0
PKG_RELEASE:=2
PKG_LICENSE:=MIT GPL-3.0-only
PKGARCH:=all
PKG_FILE_DEPENDS:=$(CURDIR)/payload.json $(CURDIR)/../alwayroute-external-manager/tools/stage-files.py $(foreach input,$(shell python3 $(CURDIR)/../alwayroute-external-manager/tools/stage-files.py --manifest $(CURDIR)/payload.json --list-sources),$(TOPDIR)/package/$(input))

include $(INCLUDE_DIR)/package.mk

define Package/luci-app-alwayroute-external
  SECTION:=net
  CATEGORY:=Network
  TITLE:=AlwayRoute optional external LuCI
  DEPENDS:=+luci-base +alwayroute-external-manager
  CONFLICTS:=luci-app-alwayroute
endef

define Build/Prepare
	python3 $(CURDIR)/../alwayroute-external-manager/tools/stage-files.py --manifest $(CURDIR)/payload.json --source-root $(TOPDIR)/package --output $(PKG_BUILD_DIR)/payload
endef

define Build/Compile
endef

define Package/luci-app-alwayroute-external/install
	$(CP) $(PKG_BUILD_DIR)/payload/. $(1)/
endef

# Match LuCI's normal package cache refresh; no service activation.
define Package/luci-app-alwayroute-external/postinst
[ -n "$${IPKG_INSTROOT}" ] || { \
	rm -f /tmp/luci-indexcache.*; \
	/etc/init.d/rpcd reload 2>/dev/null; \
	exit 0; \
}
endef

$(eval $(call BuildPackage,luci-app-alwayroute-external))
