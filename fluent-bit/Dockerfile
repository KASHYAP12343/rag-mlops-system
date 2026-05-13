FROM fluent/fluent-bit:3.0

# Copy configuration files into the image
COPY fluent-bit.conf /fluent-bit/etc/fluent-bit.conf
COPY parsers.conf    /fluent-bit/etc/parsers.conf

# Expose Fluent Bit HTTP server for health/metrics
EXPOSE 2020

CMD ["/fluent-bit/bin/fluent-bit", "-c", "/fluent-bit/etc/fluent-bit.conf"]
