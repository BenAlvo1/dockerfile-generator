FROM alpine:3.19

COPY line_counter.sh /line_counter.sh

RUN chmod +x /line_counter.sh && \
    apk add --no-cache bash

ENTRYPOINT ["/line_counter.sh"]