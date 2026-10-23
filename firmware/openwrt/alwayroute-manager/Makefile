include $(TOPDIR)/rules.mk

PKG_NAME:=alwayroute-manager
PKG_VERSION:=1.0.0
PKG_RELEASE:=3
PKG_LICENSE:=MIT
PKGARCH:=all

include $(INCLUDE_DIR)/package.mk

# package.mk tracks CURDIR recursively, including the installed policies JSON.

define Package/alwayroute-manager
  SECTION:=net
  CATEGORY:=Network
  TITLE:=AlwayRoute transactional configuration manager
  DEPENDS:=+alwayroute-core +alwayroute-forwarding +rpcd-mod-ucode +ucode +ucode-mod-fs +ucode-mod-digest +uclient-fetch +ca-bundle
endef

define Package/alwayroute-manager/conffiles
/etc/alwayroute/
endef

define Build/Compile
endef

define Package/alwayroute-manager/install
	$(INSTALL_DIR) $(1)/usr/share/ucode/alwayroute $(1)/usr/share/rpcd/ucode $(1)/usr/share/rpcd/acl.d $(1)/usr/libexec $(1)/etc/init.d $(1)/etc/uci-defaults
	$(INSTALL_DIR) $(1)/usr/share/alwayroute/policies
	$(INSTALL_DATA) ./files/usr/share/alwayroute/policies/*.json $(1)/usr/share/alwayroute/policies/
	$(INSTALL_DATA) ./files/usr/share/ucode/alwayroute/*.uc $(1)/usr/share/ucode/alwayroute/
	$(INSTALL_DATA) ./files/usr/share/rpcd/ucode/alwayroute $(1)/usr/share/rpcd/ucode/
	$(INSTALL_DATA) ./files/usr/share/rpcd/acl.d/alwayroute.json $(1)/usr/share/rpcd/acl.d/
	$(INSTALL_BIN) ./files/usr/libexec/alwayroute-* $(1)/usr/libexec/
	$(INSTALL_BIN) ./files/etc/init.d/alwayroute $(1)/etc/init.d/
	$(INSTALL_BIN) ./files/etc/uci-defaults/95-alwayroute-schedule $(1)/etc/uci-defaults/
endef

$(eval $(call BuildPackage,alwayroute-manager))
