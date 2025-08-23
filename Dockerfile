FROM ubuntu:latest
LABEL authors="ronny"

ENTRYPOINT ["top", "-b"]