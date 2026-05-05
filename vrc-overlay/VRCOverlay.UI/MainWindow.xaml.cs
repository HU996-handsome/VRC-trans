using System.Net.Http;
using System.Text.Json;
using System.Windows;
using System.Windows.Threading;

namespace VRCOverlay.UI;

public partial class MainWindow : Window
{
    private readonly HttpClient _http = new();
    private readonly DispatcherTimer _timer;
    private string _apiUrl = "http://127.0.0.1:5001/api/overlay";
    private string _settingsUrl = "http://127.0.0.1:5001";
    private bool _isDragging;

    public MainWindow()
    {
        InitializeComponent();

        // Load settings
        LoadConfig();

        // Setup polling timer
        _timer = new DispatcherTimer
        {
            Interval = TimeSpan.FromMilliseconds(500)
        };
        _timer.Tick += async (s, e) => await PollData();
        _timer.Start();

        // Make window draggable
        MouseLeftButtonDown += (s, e) =>
        {
            if (!_isDragging)
            {
                DragMove();
            }
        };

        // Double-click to toggle resize mode
        MouseDoubleClick += (s, e) =>
        {
            ResizeMode = ResizeMode == System.Windows.ResizeMode.CanResizeWithGrip
                ? System.Windows.ResizeMode.NoResize
                : System.Windows.ResizeMode.CanResizeWithGrip;
        };

        Closing += (s, e) => SaveConfig();
    }

    private async Task PollData()
    {
        try
        {
            var response = await _http.GetStringAsync(_apiUrl);
            var data = JsonSerializer.Deserialize<OverlayData>(response, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            });

            if (data != null)
            {
                Dispatcher.Invoke(() =>
                {
                    // Outgoing (my speech)
                    OutgoingTranslated.Text = string.IsNullOrEmpty(data.Out) ? "-" : data.Out;
                    OutgoingTranslated.Opacity = data.OutPartial ? 0.6 : 1.0;

                    // Incoming (others' speech)
                    IncomingTranslated.Text = string.IsNullOrEmpty(data.In) ? "-" : data.In;
                    IncomingTranslated.Opacity = data.InPartial ? 0.6 : 1.0;

                    StatusText.Text = "●";
                    StatusText.Foreground = new System.Windows.Media.SolidColorBrush(
                        System.Windows.Media.Color.FromRgb(0x81, 0xC7, 0x84));
                });
            }
        }
        catch (Exception)
        {
            Dispatcher.Invoke(() =>
            {
                StatusText.Text = "○";
                StatusText.Foreground = new System.Windows.Media.SolidColorBrush(
                    System.Windows.Media.Color.FromRgb(0x88, 0x88, 0x88));
            });
        }
    }

    private void BtnSettings_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new SettingsDialog(_apiUrl.Replace("/api/overlay", ""), _settingsUrl)
        {
            Owner = this
        };
        if (dialog.ShowDialog() == true)
        {
            _apiUrl = dialog.ApiUrl + "/api/overlay";
            _settingsUrl = dialog.SettingsUrl;
            SaveConfig();
        }
    }

    private void LoadConfig()
    {
        try
        {
            var configPath = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "VRCOverlay", "config.json");

            if (File.Exists(configPath))
            {
                var json = File.ReadAllText(configPath);
                var config = JsonSerializer.Deserialize<ConfigData>(json, new JsonSerializerOptions
                {
                    PropertyNameCaseInsensitive = true
                });
                if (config != null)
                {
                    if (!string.IsNullOrEmpty(config.ApiUrl))
                    {
                        _apiUrl = config.ApiUrl;
                        _settingsUrl = config.ApiUrl.Replace("/api/overlay", "");
                    }
                    if (config.Width > 0) Width = config.Width;
                    if (config.Height > 0) Height = config.Height;
                    if (!double.IsNaN(config.Left)) Left = config.Left;
                    if (!double.IsNaN(config.Top)) Top = config.Top;
                }
            }
        }
        catch { }
    }

    private void SaveConfig()
    {
        try
        {
            var dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "VRCOverlay");
            Directory.CreateDirectory(dir);

            var config = new ConfigData
            {
                ApiUrl = _apiUrl,
                Width = (int)Width,
                Height = (int)Height,
                Left = Left,
                Top = Top
            };

            var json = JsonSerializer.Serialize(config, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(Path.Combine(dir, "config.json"), json);
        }
        catch { }
    }

    private class OverlayData
    {
        public string Out { get; set; } = "";
        public string In { get; set; } = "";
        public bool OutPartial { get; set; }
        public bool InPartial { get; set; }
    }

    private class ConfigData
    {
        public string ApiUrl { get; set; } = "";
        public int Width { get; set; }
        public int Height { get; set; }
        public double Left { get; set; } = double.NaN;
        public double Top { get; set; } = double.NaN;
    }
}
