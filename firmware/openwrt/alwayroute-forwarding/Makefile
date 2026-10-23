include $(TOPDIR)/rules.mk

PKG_NAME:=alwayroute-forwarding
PKG_VERSION:=1
PKG_RELEASE:=1
PKG_LICENSE:=MIT
PKGARCH:=all

include $(INCLUDE_DIR)/package.mk

define Package/alwayroute-forwarding
  SECTION:=net
  CATEGORY:=Network
  TITLE:=AlwayRoute LAN forwarding adapter
  DEPENDS:=+alwayroute-core +firewall4 +jsonfilter +ip-full +ubus
endef

define Build/Compile
endef

define Package/alwayroute-forwarding/install
	$(INSTALL_DIR) $(1)/usr/libexec
	$(INSTALL_BIN) ./files/alwayroute-forwarding $(1)/usr/libexec/alwayroute-forwarding
endef

$(eval $(call BuildPackage,alwayroute-forwarding))
