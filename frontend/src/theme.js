// 全局黑白主题：近黑文字 + 纯白底 + 灰分割线，主色用近黑（不引入彩色）。
export const themeConfig = {
  token: {
    colorPrimary: '#111111',
    colorInfo: '#111111',
    colorSuccess: '#111111',
    colorWarning: '#111111',
    colorError: '#111111',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#e6e6e6',
    colorBorderSecondary: '#f0f0f0',
    colorText: '#111111',
    colorTextSecondary: '#5c5c5c',
    colorTextTertiary: '#8c8c8c',
    borderRadius: 10,
    fontFamily:
      '-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif',
    fontSize: 14,
    lineWidth: 1
  },
  components: {
    Button: { primaryShadow: 'none', borderRadius: 10 },
    Card: { borderRadius: 14 },
    Layout: { bodyBg: '#ffffff', headerBg: '#ffffff', siderBg: '#ffffff' }
  }
}
