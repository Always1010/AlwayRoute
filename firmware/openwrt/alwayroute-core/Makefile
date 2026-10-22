include $(TOPDIR)/rules.mk

PKG_NAME:=alwayroute-core
PKG_VERSION:=1.13.21
PKG_RELEASE:=1
PKG_LICENSE:=GPL-3.0-or-later
PKG_FILE_DEPENDS:=$(TOPDIR)/alwayroute-input/sing-box \
	$(TOPDIR)/alwayroute-input/build-info.json \
	$(TOPDIR)/alwayroute-input/LICENSE

include $(INCLUDE_DIR)/package.mk

# Preserve the exact externally built and device-tested ELF payload.
RSTRIP:=:

define Package/alwayroute-core
  SECTION:=net
  CATEGORY:=Network
  TITLE:=AlwayRoute static sing-box evaluation core
  DEPENDS:=+ca-bundle +kmod-nft-tproxy +ip-tiny
endef

define Package/alwayroute-core/description
  Fixed, externally built static MIPSLE softfloat sing-box core.
  This evaluation package does not enable forwarding or install a proxy UI.
endef

define Build/Prepare
	$(INSTALL_DIR) $(PKG_BUILD_DIR)
	$(CP) $(TOPDIR)/alwayroute-input/sing-box $(PKG_BUILD_DIR)/sing-box
	$(CP) $(TOPDIR)/alwayroute-input/build-info.json $(PKG_BUILD_DIR)/build-info.json
	$(CP) $(TOPDIR)/alwayroute-input/LICENSE $(PKG_BUILD_DIR)/LICENSE
endef

define Build/Compile
endef

define Package/alwayroute-core/install
	$(INSTALL_DIR) $(1)/usr/bin $(1)/usr/share/alwayroute
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/sing-box $(1)/usr/bin/sing-box
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/build-info.json $(1)/usr/share/alwayroute/build-info.json
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/LICENSE $(1)/usr/share/alwayroute/LICENSE
endef

$(eval $(call BuildPackage,alwayroute-core))
