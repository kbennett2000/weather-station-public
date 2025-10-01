const React = window.React;
const { useState, useEffect } = React;
const _ = window._;
const Papa = window.Papa;

const WeatherAnalysis = () => {
  const [analysisData, setAnalysisData] = useState({
    pressureTrends: {
      shortTerm: { rate: 0, pattern: "stable" },
      mediumTerm: { rate: 0, pattern: "stable" },
      longTerm: { rate: 0, pattern: "stable" },
    },
    temperatureHumidity: {
      dewpointSpread: 0,
      stabilityIndex: 0,
      trend: "stable",
    },
    alerts: [],
  });

  useEffect(() => {
    let mounted = true;

    const calculatePressureTrends = (data) => {
      const shortTermData = data.slice(-5);
      const mediumTermData = data.slice(-15);
      const longTermData = data.slice(-60);

      const calculateTrend = (readings) => {
        if (readings.length < 2) return { rate: 0, pattern: "stable" };

        const rates = [];
        for (let i = 1; i < readings.length; i++) {
          rates.push((readings[i].pressure - readings[i - 1].pressure) / ((new Date(readings[i].timestamp) - new Date(readings[i - 1].timestamp)) / 3600000));
        }

        const avgRate = _.mean(rates);
        let pattern = "stable";
        if (Math.abs(avgRate) > 0.06) pattern = avgRate > 0 ? "rapid-rise" : "rapid-fall";
        else if (Math.abs(avgRate) > 0.02) pattern = avgRate > 0 ? "rise" : "fall";

        return { rate: avgRate, pattern };
      };

      return {
        shortTerm: calculateTrend(shortTermData),
        mediumTerm: calculateTrend(mediumTermData),
        longTerm: calculateTrend(longTermData),
      };
    };

    const analyzeTempHumidity = (data) => {
      const recent = data.slice(-30);
      const dewpoints = recent.map((reading) => calculateDewPoint(reading.temperatureC, reading.humidity));

      const currentTemp = recent[recent.length - 1].temperatureC;
      const currentDewpoint = dewpoints[dewpoints.length - 1];
      const spreadTrend = (dewpoints[dewpoints.length - 1] - dewpoints[0]) / ((new Date(recent[recent.length - 1].timestamp) - new Date(recent[0].timestamp)) / 3600000);

      const tempHumidityCorrelation = calculateCorrelation(
        recent.map((r) => r.temperatureC),
        recent.map((r) => r.humidity)
      );

      let trend = "stable";
      if (spreadTrend < -1) trend = "improving";
      else if (spreadTrend > 1) trend = "deteriorating";

      return {
        dewpointSpread: currentTemp - currentDewpoint,
        stabilityIndex: tempHumidityCorrelation,
        trend,
      };
    };

    const generateAlerts = (pressureTrends, tempHumidity) => {
      const alerts = [];

      if (Math.abs(pressureTrends.shortTerm.rate) > 0.06) {
        alerts.push({
          severity: "high",
          message: `Rapid pressure ${pressureTrends.shortTerm.rate > 0 ? "rise" : "fall"} detected`,
          description: "Significant weather changes likely in the next 6-12 hours",
        });
      }

      if (tempHumidity.dewpointSpread < 2.5) {
        alerts.push({
          severity: "high",
          message: "Conditions favorable for precipitation or fog",
          description: "High humidity with temperature close to dewpoint",
        });
      }

      return alerts;
    };

    const loadAndAnalyzeData = async () => {
      try {
        // Fetch more data for analysis - get last 3 days
        const response = await fetch("/weather_data_outdoor.csv?hours=72");
        const text = await response.text();

        if (!mounted) return;

        Papa.parse(text, {
          header: true,
          dynamicTyping: true,
          skipEmptyLines: true,
          complete: (results) => {
            if (!mounted) return;

            // Filter out invalid data
            const validData = results.data.filter((row) => row.timestamp && row.pressure && row.temperatureC && row.humidity && !isNaN(parseFloat(row.pressure)) && !isNaN(parseFloat(row.temperatureC)) && !isNaN(parseFloat(row.humidity)));

            if (validData.length < 5) {
              console.log("Not enough valid data for analysis");
              setAnalysisData({
                pressureTrends: {
                  shortTerm: { rate: 0, pattern: "stable" },
                  mediumTerm: { rate: 0, pattern: "stable" },
                  longTerm: { rate: 0, pattern: "stable" },
                },
                temperatureHumidity: {
                  dewpointSpread: 0,
                  stabilityIndex: 0,
                  trend: "stable",
                },
                alerts: [
                  {
                    severity: "medium",
                    message: "Insufficient data for analysis",
                    description: "More data collection is needed for accurate forecasts",
                  },
                ],
              });
              return;
            }

            const recentData = validData.slice(-120); // Take more recent samples

            const pressureTrends = calculatePressureTrends(recentData);
            const tempHumidity = analyzeTempHumidity(recentData);
            const alerts = generateAlerts(pressureTrends, tempHumidity);

            setAnalysisData({
              pressureTrends,
              temperatureHumidity: tempHumidity,
              alerts,
            });
          },
          error: (error) => {
            console.error("CSV parsing error:", error);
          },
        });
      } catch (error) {
        if (mounted) {
          console.error("Error loading data:", error);
        }
      }
    };

    loadAndAnalyzeData();
    const interval = setInterval(loadAndAnalyzeData, 60000);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const calculateDewPoint = (tempC, humidity) => {
    const a = 17.27;
    const b = 237.7;
    const gamma = (a * tempC) / (b + tempC) + Math.log(humidity / 100.0);
    return (b * gamma) / (a - gamma);
  };

  const calculateCorrelation = (arr1, arr2) => {
    const mean1 = _.mean(arr1);
    const mean2 = _.mean(arr2);
    const nums = arr1.map((x, i) => (x - mean1) * (arr2[i] - mean2));
    const den = Math.sqrt(arr1.reduce((acc, x) => acc + (x - mean1) ** 2, 0) * arr2.reduce((acc, x) => acc + (x - mean2) ** 2, 0));
    return nums.reduce((acc, x) => acc + x, 0) / den;
  };

  const getPatternColor = (pattern) => {
    switch (pattern) {
      case "rapid-rise":
        return "text-red-600";
      case "rapid-fall":
        return "text-blue-600";
      case "rise":
        return "text-orange-600";
      case "fall":
        return "text-indigo-600";
      default:
        return "text-gray-600";
    }
  };

  const getTrendEmoji = (pattern) => {
    switch (pattern) {
      case "rapid-rise":
        return "⬆️";
      case "rapid-fall":
        return "⬇️";
      case "rise":
        return "↗️";
      case "fall":
        return "↘️";
      default:
        return "↔️";
    }
  };

  const getStabilityDescription = (index) => {
    if (index <= -0.8) return "Strong stability - strong temperature/humidity opposition, very stable air, clear skies likely, dry conditions";
    if (index <= -0.4) return "Moderate stability - generally fair weather, low precipitation chance";
    if (index <= -0.1) return "Slight stability - normal conditions, weather changes possible but not imminent";
    if (index < 0.1) return "No relationship - transition period or changing conditions";
    if (index < 0.4) return "Mild instability - increasing moisture possible";
    if (index < 0.8) return "Moderate instability - precipitation becoming likely, storms possible";
    return "Strong instability - high storm probability, significant precipitation likely";
  };

  const getOverallStabilityTrendDescription = () => {
    return "Calculated from change in dewpoint spread over time.\nValues indicate:\n- improving: Dewpoint spread is decreasing significantly (< -1°C/hr), suggesting more stable conditions\n- stable: Minimal change in dewpoint spread (-1 to 1°C/hr)\n- deteriorating: Dewpoint spread increasing significantly (> 1°C/hr), suggesting destabilizing conditions\nThis metric helps forecast short-term stability changes and potential weather shifts.";
  };

  const getStabilityIndexPercentage = (index) => {
    return (-index * 100).toFixed(2) + "%";
  };

  const AnalysisTrends = () => {
    const [trends, setTrends] = useState({
      pressure: { hourlyAvg: null, stdDev: null, correlation: { temp: null, humidity: null } },
      temperature: { hourlyAvg: null, stdDev: null },
    });

    useEffect(() => {
      let mounted = true;

      const calculateMovingAverage = (data, period = 60) => {
        if (!data || data.length < period) return null;
        const validData = data.filter((x) => x !== null && !isNaN(x));
        if (validData.length < period) return null;

        return validData
          .map((value, index, array) => {
            if (index < period - 1) return null;
            const slice = array.slice(index - period + 1, index + 1);
            return _.mean(slice);
          })
          .filter((x) => x !== null && !isNaN(x));
      };

      const calculateStdDev = (data) => {
        if (!data || data.length === 0) return null;
        const validData = data.filter((x) => x !== null && !isNaN(x));
        if (validData.length === 0) return null;

        const mean = _.mean(validData);
        const squareDiffs = validData.map((value) => Math.pow(value - mean, 2));
        return Math.sqrt(_.mean(squareDiffs));
      };

      const calculateCorrelation = (data1, data2) => {
        if (!data1 || !data2 || data1.length === 0 || data2.length === 0) return null;
        const pairs = _.zip(data1, data2).filter(([a, b]) => a !== null && !isNaN(a) && b !== null && !isNaN(b));
        if (pairs.length === 0) return null;

        const [validData1, validData2] = _.unzip(pairs);
        const mean1 = _.mean(validData1);
        const mean2 = _.mean(validData2);

        const nums = validData1.map((x, i) => (x - mean1) * (validData2[i] - mean2));
        const den = Math.sqrt(validData1.reduce((acc, x) => acc + Math.pow(x - mean1, 2), 0) * validData2.reduce((acc, x) => acc + Math.pow(x - mean2, 2), 0));

        return nums.reduce((acc, x) => acc + x, 0) / den;
      };

      async function fetchAndAnalyze() {
        try {
          // Getting 5 days of data for better statistical analysis
          const response = await fetch("/weather_data_outdoor.csv?hours=120");
          const text = await response.text();

          if (!mounted) return;

          Papa.parse(text, {
            header: true,
            dynamicTyping: true,
            skipEmptyLines: true,
            complete: (results) => {
              if (!mounted) return;

              const pressureData = results.data.map((d) => d.pressure).filter((p) => p !== null);
              const tempData = results.data.map((d) => d.temperatureC).filter((t) => t !== null);
              const humidityData = results.data.map((d) => d.humidity).filter((h) => h !== null);

              if (pressureData.length > 0 && tempData.length > 0 && humidityData.length > 0) {
                setTrends({
                  pressure: {
                    hourlyAvg: calculateMovingAverage(pressureData),
                    stdDev: calculateStdDev(pressureData),
                    correlation: {
                      temp: calculateCorrelation(pressureData.slice(-60), tempData.slice(-60)),
                      humidity: calculateCorrelation(pressureData.slice(-60), humidityData.slice(-60)),
                    },
                  },
                  temperature: {
                    hourlyAvg: calculateMovingAverage(tempData),
                    stdDev: calculateStdDev(tempData),
                  },
                });
              }
            },
          });
        } catch (error) {
          if (mounted) {
            console.error("Data loading error:", error);
          }
        }
      }

      fetchAndAnalyze();
      const interval = setInterval(fetchAndAnalyze, 300000);

      return () => {
        mounted = false;
        clearInterval(interval);
      };
    }, []);

    const getPressureStandardDeviationDescription = () => {
      return "Measures pressure variability.\nHigher values (>0.5 hPa) indicate unstable conditions.";
    };

    const getCorrelationWithTemperatureDescription = () => {
      return "-1 to 1 scale showing pressure-temperature relationship.\nNegative values mean pressure drops as temperature rises.\nStrong Positive (near +1):\n- Temperature and pressure rise/fall together\n- Less common, can indicate high-pressure system dominance\n- Often associated with stable conditions\nStrong Negative (near -1):\n- As temperature rises, pressure falls (and vice versa)\n- Common in normal weather patterns\n- Can indicate convective activity/storm potential";
    };

    const getCorrelationWithHumidityDescription = () => {
      return "-1 to 1 scale showing pressure-humidity relationship.\nPositive values suggest pressure rises with humidity.\nStrong Positive (near +1):\n- Temperature and humidity rise/fall together\n- Can indicate moisture influx\n- Common before precipitation\nStrong Negative (near -1):\n- As temperature rises, humidity falls\n- Typical of clear, stable conditions\n- Indicates drier air mass";
    };

    const getTemperatureStandardDeviationDescription = () => {
      return "Measures temperature variability.\nHigher values (>2°C) indicate unstable temperature patterns.";
    };

    const getHourMovingAverageDescription = () => {
      return "Average temperature over last 60 minutes, smoothing out short-term fluctuations.";
    };

    return (
      <div className="bg-white rounded-lg shadow-lg p-6">
        <h2 className="text-2xl font-bold text-gray-800 mb-6">Statistical Trends</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="p-4 rounded-lg bg-blue-50">
            <h3 className="font-semibold text-blue-800 mb-4">Pressure Statistics</h3>
            <div className="space-y-2">
              <p title={getPressureStandardDeviationDescription()}>Standard Deviation: {trends.pressure.stdDev?.toFixed(3) || "N/A"} hPa</p>
              <p title={getCorrelationWithTemperatureDescription()}>Correlation with Temperature: {trends.pressure.correlation.temp?.toFixed(3) || "N/A"}</p>
              <p title={getCorrelationWithHumidityDescription()}>Correlation with Humidity: {trends.pressure.correlation.humidity?.toFixed(3) || "N/A"}</p>
            </div>
          </div>
          <div className="p-4 rounded-lg bg-green-50">
            <h3 className="font-semibold text-green-800 mb-4">Temperature Statistics</h3>
            <div className="space-y-2">
              <p title={getTemperatureStandardDeviationDescription()}>Standard Deviation: {trends.temperature.stdDev?.toFixed(3) || "N/A"}°C</p>
              <p title={getHourMovingAverageDescription()}>Hour Moving Average: {trends.temperature.hourlyAvg?.slice(-1)[0]?.toFixed(2) || "N/A"}°C</p>
            </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="max-w-7xl mx-auto p-4 space-y-6">
      {/* Alert Section */}
      {analysisData.alerts.length > 0 && (
        <div className="bg-gradient-to-r from-orange-50 to-red-50 rounded-lg shadow-lg p-6 border-l-4 border-red-500">
          <h2 className="text-2xl font-bold text-red-800 mb-4">Weather Alerts</h2>
          <div className="space-y-4">
            {analysisData.alerts.map((alert, index) => (
              <div key={index} className="flex flex-col">
                <span className="text-lg font-semibold text-red-700">{alert.message}</span>
                <span className="text-sm text-red-600">{alert.description}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Pressure Analysis */}
      <div className="bg-white rounded-lg shadow-lg p-6">
        <h2 className="text-2xl font-bold text-gray-800 mb-6">Pressure Trend Analysis</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {Object.entries(analysisData.pressureTrends).map(([period, data]) => (
            <div key={period} className="p-4 rounded-lg bg-gradient-to-br from-gray-50 to-gray-100 border border-gray-200">
              <h3 className="font-semibold text-gray-700 capitalize mb-2">{period.replace(/([A-Z])/g, " $1")}</h3>
              <div className="space-y-2">
                <p className="text-lg">
                  <span className="font-medium">Rate: </span>
                  <span className={getPatternColor(data.pattern)}>{data.rate.toFixed(3)} hPa/hr</span>
                </p>
                <p className="text-lg flex items-center gap-2">
                  <span className="font-medium">Pattern: </span>
                  <span className={`capitalize ${getPatternColor(data.pattern)}`}>
                    {data.pattern} {getTrendEmoji(data.pattern)}
                  </span>
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Temperature-Humidity Analysis */}
      <div className="bg-white rounded-lg shadow-lg p-6">
        <h2 className="text-2xl font-bold text-gray-800 mb-6">Temperature-Humidity Analysis</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Dewpoint Spread */}
          <div title="temp - dewpoint" className="p-4 rounded-lg bg-gradient-to-br from-blue-50 to-blue-100 border border-blue-200">
            <h3 className="font-semibold text-blue-800 mb-2">Dewpoint Spread</h3>
            <p className="text-2xl text-blue-700">{analysisData.temperatureHumidity.dewpointSpread.toFixed(1)}°C</p>
          </div>
          {/* Stability Index */}
          <div className="p-4 rounded-lg bg-gradient-to-br from-purple-50 to-purple-100 border border-purple-200" title={getStabilityDescription(analysisData.temperatureHumidity.stabilityIndex)}>
            <h3 className="font-semibold text-purple-800 mb-2">Stability Index</h3>
            <p className="text-2xl text-purple-700">
              {getStabilityIndexPercentage(analysisData.temperatureHumidity.stabilityIndex)} ({analysisData.temperatureHumidity.stabilityIndex.toFixed(2)})
            </p>
          </div>
          {/* Overall Stability Trend */}
          <div title={getOverallStabilityTrendDescription()} className="p-4 rounded-lg bg-gradient-to-br from-green-50 to-green-100 border border-green-200">
            <h3 className="font-semibold text-green-800 mb-2">Overall Stability Trend</h3>
            <p className="text-2xl capitalize text-green-700">{analysisData.temperatureHumidity.trend}</p>
          </div>
        </div>
      </div>

      {/* Trends Analysis */}
      <AnalysisTrends />
    </div>
  );
};

window.WeatherAnalysis = WeatherAnalysis;
