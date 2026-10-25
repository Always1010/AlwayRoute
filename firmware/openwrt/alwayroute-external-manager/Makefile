include $(TOPDIR)/rules.mk

PKG_NAME:=alwayroute-external-manager
PKG_VERSION:=1.0.0
PKG_RELEASE:=2
PKG_LICENSE:=MIT GPL-3.0-only
PKGARCH:=all
PKG_FILE_DEPENDS:=$(CURDIR)/payload.json $(CURDIR)/../alwayroute-external-manager/tools/stage-files.py $(foreach input,$(shell python3 $(CURDIR)/../alwayroute-external-manager/tools/stage-files.py --manifest $(CURDIR)/payload.json --list-sources),$(TOPDIR)/package/$(input))

include $(INCLUDE_DIR)/package.mk

define Package/alwayroute-external-manager
  SECTION:=net
  CATEGORY:=Network
  TITLE:=AlwayRoute optional external manager
  DEPENDS:=+alwayroute-external-forwarding +rpcd-mod-ucode +ucode +ucode-mod-fs +ubus +dnsmasq +busybox
  CONFLICTS:=alwayroute-manager alwayroute-forwarding
endef

define Package/alwayroute-external-manager/conffiles
/etc/alwayroute/
endef

define Build/Prepare
	python3 $(CURDIR)/../alwayroute-external-manager/tools/stage-files.py --manifest $(CURDIR)/payload.json --source-root $(TOPDIR)/package --output $(PKG_BUILD_DIR)/payload
endef

define Build/Compile
endef

define Package/alwayroute-external-manager/install
	$(CP) $(PKG_BUILD_DIR)/payload/. $(1)/
endef

$(eval $(call BuildPackage,alwayroute-external-manager))
